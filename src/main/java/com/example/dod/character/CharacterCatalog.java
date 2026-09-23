package com.example.dod.character;

import com.example.dod.config.PrototypeProperties;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class CharacterCatalog {
    private static final Logger log = LoggerFactory.getLogger(CharacterCatalog.class);

    private final ObjectMapper objectMapper;
    private final PrototypeProperties properties;
    private volatile List<CharacterInfo> characters = List.of();

    public CharacterCatalog(ObjectMapper objectMapper, PrototypeProperties properties) {
        this.objectMapper = objectMapper;
        this.properties = properties;
    }

    @PostConstruct
    void load() {
        Path manifest = Path.of(properties.characters().directory()).resolve("manifest.json");
        if (!Files.exists(manifest)) {
            log.warn("Character manifest not found at {}", manifest.toAbsolutePath());
            characters = List.of();
            return;
        }

        try {
            CharacterInfo[] loadedCharacters = objectMapper.readValue(manifest.toFile(), CharacterInfo[].class);
            characters = List.copyOf(Arrays.asList(loadedCharacters));
            log.info("Loaded {} characters from {}", characters.size(), manifest.toAbsolutePath());
        } catch (JacksonException e) {
            throw new IllegalStateException("Failed to load character manifest " + manifest.toAbsolutePath(), e);
        }
    }

    public List<CharacterInfo> findAll() {
        return characters;
    }

    public Optional<CharacterInfo> findById(String id) {
        return characters.stream()
                .filter(character -> character.id().equals(id))
                .findFirst();
    }
}
