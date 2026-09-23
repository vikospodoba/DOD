package com.example.dod.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "dod")
public record PrototypeProperties(
        Worker worker,
        Characters characters,
        WebSocket webSocket
) {
    public PrototypeProperties {
        if (worker == null) {
            worker = new Worker("http://127.0.0.1:8001", Duration.ofSeconds(10), null, 8002);
        }
        if (characters == null) {
            characters = new Characters("characters", "default-human");
        }
        if (webSocket == null) {
            webSocket = new WebSocket("*", 8 * 1024 * 1024);
        }
    }

    public record Worker(String baseUrl, Duration timeout, String frameHost, int framePort) {
        public Worker {
            if (framePort <= 0) {
                framePort = 8002;
            }
        }
    }

    public record Characters(String directory, String defaultCharacterId) {
    }

    public record WebSocket(String allowedOrigins, int messageSizeLimitBytes) {
        public WebSocket {
            if (messageSizeLimitBytes <= 0) {
                messageSizeLimitBytes = 8 * 1024 * 1024;
            }
        }
    }
}
