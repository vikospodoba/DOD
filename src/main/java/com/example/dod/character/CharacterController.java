package com.example.dod.character;

import com.example.dod.worker.WorkerCharacterResult;
import com.example.dod.worker.WorkerClient;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/characters")
public class CharacterController {
    private final CharacterCatalog catalog;
    private final WorkerClient workerClient;

    public CharacterController(CharacterCatalog catalog, WorkerClient workerClient) {
        this.catalog = catalog;
        this.workerClient = workerClient;
    }

    @GetMapping
    public List<CharacterInfo> listCharacters() {
        return catalog.findAll();
    }

    @PostMapping("/{characterId}/prepare")
    public CharacterSelectionResponse prepareCharacter(@PathVariable String characterId) {
        requireKnownCharacter(characterId);
        WorkerCharacterResult result = workerClient.prepareCharacter(characterId);
        if (!"ok".equals(result.status())) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, result.status());
        }
        return new CharacterSelectionResponse(result.status(), result.characterId(), result.selectedCharacterId());
    }

    @PostMapping("/{characterId}/select")
    public CharacterSelectionResponse selectCharacter(@PathVariable String characterId) {
        requireKnownCharacter(characterId);
        WorkerCharacterResult prepareResult = workerClient.prepareCharacter(characterId);
        if (!"ok".equals(prepareResult.status())) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, prepareResult.status());
        }

        WorkerCharacterResult selectResult = workerClient.selectCharacter(characterId);
        if (!"ok".equals(selectResult.status())) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, selectResult.status());
        }
        return new CharacterSelectionResponse(
                selectResult.status(),
                selectResult.characterId(),
                selectResult.selectedCharacterId()
        );
    }

    private void requireKnownCharacter(String characterId) {
        if (catalog.findById(characterId).isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown character: " + characterId);
        }
    }
}
