package com.example.dod.video;

import com.example.dod.config.PrototypeProperties;
import com.example.dod.worker.WorkerClient;
import com.example.dod.worker.WorkerFrameResult;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.time.Clock;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.BinaryMessage;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.BinaryWebSocketHandler;
import tools.jackson.databind.ObjectMapper;

@Component
public class VideoWebSocketHandler extends BinaryWebSocketHandler {
    private static final Logger log = LoggerFactory.getLogger(VideoWebSocketHandler.class);
    private static final int MAX_IN_FLIGHT_FRAMES_PER_SESSION = 2;

    private final WorkerClient workerClient;
    private final BinaryFrameCodec frameCodec;
    private final Clock clock;
    private final ExecutorService executorService;
    private final Map<String, SessionState> sessions = new ConcurrentHashMap<>();
    private final int messageSizeLimitBytes;

    public VideoWebSocketHandler(
            WorkerClient workerClient,
            ObjectMapper objectMapper,
            PrototypeProperties properties
    ) {
        this.workerClient = workerClient;
        this.frameCodec = new BinaryFrameCodec(objectMapper);
        this.clock = Clock.systemUTC();
        this.executorService = Executors.newVirtualThreadPerTaskExecutor();
        this.messageSizeLimitBytes = properties.webSocket().messageSizeLimitBytes();
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        session.setBinaryMessageSizeLimit(messageSizeLimitBytes);
        session.setTextMessageSizeLimit(messageSizeLimitBytes);
        sessions.put(session.getId(), new SessionState());
        log.info("Video session connected: {}", session.getId());
    }

    @Override
    protected void handleBinaryMessage(WebSocketSession session, BinaryMessage message) throws IOException {
        SessionState state = sessions.computeIfAbsent(session.getId(), ignored -> new SessionState());
        if (!state.tryAcquireFrameSlot()) {
            return;
        }

        byte[] payload = toByteArray(message.getPayload());
        executorService.submit(() -> processMessage(session, state, payload));
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sessions.remove(session.getId());
        log.info("Video session disconnected: {}, status={}", session.getId(), status);
    }

    private void processMessage(WebSocketSession session, SessionState state, byte[] payload) {
        long receivedAt = clock.millis();
        try {
            BinaryFrame<FrameMetadata> frame = frameCodec.decode(payload, FrameMetadata.class);
            WorkerFrameResult workerResult = workerClient.processFrame(frame.metadata(), frame.imageBytes());
            long sentAt = clock.millis();
            ProcessedFrameMetadata responseMetadata = new ProcessedFrameMetadata(
                    workerResult.status(),
                    frame.metadata().characterId(),
                    frame.metadata().sequence(),
                    frame.metadata().capturedAtEpochMs(),
                    receivedAt,
                    sentAt,
                    workerResult.inferenceMs()
            );
            byte[] response = frameCodec.encode(responseMetadata, workerResult.imageBytes());
            if (session.isOpen()) {
                state.send(session, response);
            }
        } catch (IOException e) {
            log.debug("Failed to process video frame for session {}: {}", session.getId(), e.getMessage());
        } finally {
            state.releaseFrameSlot();
        }
    }

    private static byte[] toByteArray(ByteBuffer buffer) {
        ByteBuffer copy = buffer.slice();
        byte[] payload = new byte[copy.remaining()];
        copy.get(payload);
        return payload;
    }

    private static final class SessionState {
        private final AtomicInteger inFlightFrames = new AtomicInteger();
        private final Object sendLock = new Object();

        private boolean tryAcquireFrameSlot() {
            while (true) {
                int current = inFlightFrames.get();
                if (current >= MAX_IN_FLIGHT_FRAMES_PER_SESSION) {
                    return false;
                }
                if (inFlightFrames.compareAndSet(current, current + 1)) {
                    return true;
                }
            }
        }

        private void releaseFrameSlot() {
            inFlightFrames.updateAndGet(current -> Math.max(0, current - 1));
        }

        private void send(WebSocketSession session, byte[] response) throws IOException {
            synchronized (sendLock) {
                if (session.isOpen()) {
                    session.sendMessage(new BinaryMessage(response));
                }
            }
        }
    }
}
