package com.example.dod.worker;

public record WorkerHealth(
        String status,
        boolean ready,
        double fps,
        double inferenceMs,
        long gpuMemoryUsedMb
) {
    public static WorkerHealth unavailable() {
        return new WorkerHealth("unavailable", false, 0.0, 0.0, 0L);
    }
}
