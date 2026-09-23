package com.example.dod.video;

public record ProcessedFrameMetadata(
        String status,
        String characterId,
        long sequence,
        long capturedAtEpochMs,
        long serverReceivedAtEpochMs,
        long serverSentAtEpochMs,
        long inferenceMs
) {
}
