package com.example.dod.status;

import com.example.dod.worker.WorkerClient;
import com.example.dod.worker.WorkerHealth;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/status")
public class StatusController {
    private final WorkerClient workerClient;

    public StatusController(WorkerClient workerClient) {
        this.workerClient = workerClient;
    }

    @GetMapping
    public PrototypeStatus status() {
        WorkerHealth health = workerClient.health();
        return new PrototypeStatus(
                "ok",
                health.status(),
                health.ready(),
                health.fps(),
                health.inferenceMs(),
                health.gpuMemoryUsedMb()
        );
    }
}
