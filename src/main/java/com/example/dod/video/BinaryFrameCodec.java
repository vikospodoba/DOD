package com.example.dod.video;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

public class BinaryFrameCodec {
    private static final int HEADER_LENGTH_BYTES = 4;
    private static final int MAX_HEADER_BYTES = 16 * 1024;

    private final ObjectMapper objectMapper;

    public BinaryFrameCodec(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public <T> BinaryFrame<T> decode(byte[] payload, Class<T> metadataType) throws IOException {
        if (payload.length < HEADER_LENGTH_BYTES) {
            throw new IOException("Binary frame is shorter than header length prefix");
        }

        ByteBuffer buffer = ByteBuffer.wrap(payload).order(ByteOrder.BIG_ENDIAN);
        int headerLength = buffer.getInt();
        if (headerLength <= 0 || headerLength > MAX_HEADER_BYTES) {
            throw new IOException("Invalid metadata header length: " + headerLength);
        }
        if (payload.length < HEADER_LENGTH_BYTES + headerLength) {
            throw new IOException("Binary frame payload is truncated");
        }

        byte[] header = Arrays.copyOfRange(payload, HEADER_LENGTH_BYTES, HEADER_LENGTH_BYTES + headerLength);
        byte[] image = Arrays.copyOfRange(payload, HEADER_LENGTH_BYTES + headerLength, payload.length);
        T metadata;
        try {
            metadata = objectMapper.readValue(header, metadataType);
        } catch (JacksonException e) {
            throw new IOException("Invalid frame metadata JSON", e);
        }
        return new BinaryFrame<>(metadata, image);
    }

    public byte[] encode(Object metadata, byte[] imageBytes) throws IOException {
        byte[] header;
        try {
            header = objectMapper.writeValueAsBytes(metadata);
        } catch (JacksonException e) {
            throw new IOException("Failed to encode frame metadata JSON", e);
        }
        ByteBuffer buffer = ByteBuffer.allocate(HEADER_LENGTH_BYTES + header.length + imageBytes.length)
                .order(ByteOrder.BIG_ENDIAN);
        buffer.putInt(header.length);
        buffer.put(header);
        buffer.put(imageBytes);
        return buffer.array();
    }
}
