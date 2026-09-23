package com.example.dod.config;

import java.nio.file.Path;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CharacterAssetsConfig implements WebMvcConfigurer {
    private final PrototypeProperties properties;

    public CharacterAssetsConfig(PrototypeProperties properties) {
        this.properties = properties;
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String location = Path.of(properties.characters().directory()).toAbsolutePath().toUri().toString();
        registry.addResourceHandler("/characters/**").addResourceLocations(location);
    }
}
