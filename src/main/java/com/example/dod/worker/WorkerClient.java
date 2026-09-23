package com.example.dod.worker;

import com.example.dod.config.PrototypeProperties;
import com.example.dod.video.BinaryFrame;
import com.example.dod.video.BinaryFrameCodec;
import com.example.dod.video.FrameMetadata;
import java.io.IOException;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
public class WorkerClient {
    private static final Logger log = LoggerFactory.getLogger(WorkerClient.class);

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final BinaryFrameCodec frameCodec;
    private final String baseUrl;
    private final String frameHost;
    private final int framePort;
    private final Duration timeout;
    private final Object frameSocketLock = new Object();
    private Socket frameSocket;
    private DataInputStream frameInput;
    private DataOutputStream frameOutput;

    public WorkerClient(ObjectMapper objectMapper, PrototypeProperties properties) {
        this.objectMapper = objectMapper;
        this.frameCodec = new BinaryFrameCodec(objectMapper);
        this.baseUrl = removeTrailingSlash(properties.worker().baseUrl());
        URI baseUri = URI.create(this.baseUrl);
        this.frameHost = properties.worker().frameHost() == null || properties.worker().frameHost().isBlank()
                ? baseUri.getHost()
                : properties.worker().frameHost();
        this.framePort = properties.worker().framePort();
        this.timeout = properties.worker().timeout();
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(timeout)
                .build();
    }

    public WorkerHealth health() {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + "/health"))
                .timeout(timeout)
                .GET()
                .build();

        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() / 100 != 2) {
                return WorkerHealth.unavailable();
            }
            return objectMapper.readValue(response.body(), WorkerHealth.class);
        } catch (IOException | JacksonException e) {
            log.debug("Worker health request failed: {}", e.getMessage());
            return WorkerHealth.unavailable();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return WorkerHealth.unavailable();
        }
    }

    public WorkerCharacterResult prepareCharacter(String characterId) {
        return sendCharacterCommand("/v1/prepare-character", characterId);
    }

    public WorkerCharacterResult selectCharacter(String characterId) {
        return sendCharacterCommand("/v1/select-character", characterId);
    }

    public WorkerFrameResult processFrame(FrameMetadata metadata, byte[] frameBytes) {
        synchronized (frameSocketLock) {
            try {
                return processFrameOverStream(metadata, frameBytes);
            } catch (IOException e) {
                log.debug("Worker frame stream request failed: {}", e.getMessage());
                closeFrameStream();
                try {
                    return processFrameOverStream(metadata, frameBytes);
                } catch (IOException retryError) {
                    log.debug("Worker frame stream retry failed: {}", retryError.getMessage());
                    closeFrameStream();
                    return new WorkerFrameResult("processing_error", 0L, frameBytes);
                }
            }
        }
    }

    private WorkerFrameResult processFrameOverStream(FrameMetadata metadata, byte[] frameBytes) throws IOException {
        ensureFrameStream();
        byte[] payload = frameCodec.encode(metadata, frameBytes);
        frameOutput.writeInt(payload.length);
        frameOutput.write(payload);
        frameOutput.flush();

        int responseLength = frameInput.readInt();
        if (responseLength <= 0 || responseLength > 16 * 1024 * 1024) {
            throw new IOException("Invalid worker frame response length: " + responseLength);
        }

        byte[] responsePayload = frameInput.readNBytes(responseLength);
        if (responsePayload.length != responseLength) {
            throw new IOException("Worker frame response is truncated");
        }

        BinaryFrame<WorkerFrameStreamMetadata> response = frameCodec.decode(
                responsePayload,
                WorkerFrameStreamMetadata.class
        );
        return new WorkerFrameResult(response.metadata().status(), response.metadata().inferenceMs(), response.imageBytes());
    }

    private void ensureFrameStream() throws IOException {
        if (frameSocket != null && frameSocket.isConnected() && !frameSocket.isClosed()) {
            return;
        }

        frameSocket = new Socket(frameHost, framePort);
        frameSocket.setTcpNoDelay(true);
        frameSocket.setSoTimeout(Math.toIntExact(timeout.toMillis()));
        frameInput = new DataInputStream(frameSocket.getInputStream());
        frameOutput = new DataOutputStream(frameSocket.getOutputStream());
    }

    private void closeFrameStream() {
        if (frameSocket != null) {
            try {
                frameSocket.close();
            } catch (IOException ignored) {
            }
        }
        frameSocket = null;
        frameInput = null;
        frameOutput = null;
    }

    private record WorkerFrameStreamMetadata(
            String status,
            String characterId,
            long sequence,
            long capturedAtEpochMs,
            long inferenceMs
    ) {
    }

    private WorkerCharacterResult sendCharacterCommand(String path, String characterId) {
        String body;
        try {
            body = objectMapper.writeValueAsString(new WorkerCharacterRequest(characterId));
        } catch (JacksonException e) {
            throw new IllegalStateException("Failed to encode worker character request", e);
        }

        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();

        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() / 100 != 2) {
                log.debug("Worker character command failed: path={}, status={}", path, response.statusCode());
                return new WorkerCharacterResult("processing_error", false, characterId, "");
            }
            return objectMapper.readValue(response.body(), WorkerCharacterResult.class);
        } catch (IOException | JacksonException e) {
            log.debug("Worker character command request failed: {}", e.getMessage());
            return WorkerCharacterResult.unavailable(characterId);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return WorkerCharacterResult.unavailable(characterId);
        }
    }

    private static String removeTrailingSlash(String value) {
        if (value.endsWith("/")) {
            return value.substring(0, value.length() - 1);
        }
        return value;
    }

    private static long parseLong(String value) {
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException e) {
            return 0L;
        }
    }
}
