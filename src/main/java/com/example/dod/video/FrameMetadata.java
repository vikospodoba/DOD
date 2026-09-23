package com.example.dod.video;

public record FrameMetadata(
        String characterId,
        boolean manyFaces,
        long sequence,
        long capturedAtEpochMs
) {
}
