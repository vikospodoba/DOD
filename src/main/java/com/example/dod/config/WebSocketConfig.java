package com.example.dod.config;

import com.example.dod.video.VideoWebSocketHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {
    private final VideoWebSocketHandler videoWebSocketHandler;
    private final PrototypeProperties properties;

    public WebSocketConfig(VideoWebSocketHandler videoWebSocketHandler, PrototypeProperties properties) {
        this.videoWebSocketHandler = videoWebSocketHandler;
        this.properties = properties;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(videoWebSocketHandler, "/ws/video")
                .setAllowedOrigins(properties.webSocket().allowedOrigins());
    }
}
