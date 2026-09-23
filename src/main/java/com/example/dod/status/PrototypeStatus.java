package com.example.dod.status;

public record PrototypeStatus(
        String javaService,
        String workerStatus,
        boolean workerReady,
        double workerFps,
        double workerInferenceMs,
        long gpuMemoryUsedMb
) {
}
