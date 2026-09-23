package com.example.dod.status;

import com.example.dod.worker.WorkerClient;
import com.example.dod.worker.WorkerHealth;
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.stereotype.Component;

@Component
public class WorkerHealthIndicator implements HealthIndicator {
    private final WorkerClient workerClient;

    public WorkerHealthIndicator(WorkerClient workerClient) {
        this.workerClient = workerClient;
    }

    @Override
    public Health health() {
        WorkerHealth workerHealth = workerClient.health();
        Health.Builder builder = workerHealth.ready() ? Health.up() : Health.down();
        return builder
                .withDetail("status", workerHealth.status())
                .withDetail("fps", workerHealth.fps())
                .withDetail("inferenceMs", workerHealth.inferenceMs())
                .withDetail("gpuMemoryUsedMb", workerHealth.gpuMemoryUsedMb())
                .build();
    }
}
