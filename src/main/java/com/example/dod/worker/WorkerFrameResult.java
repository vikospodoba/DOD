package com.example.dod.worker;

public record WorkerFrameResult(
        String status,
        long inferenceMs,
        byte[] imageBytes
) {
}
