package com.example.dod.character;

public record CharacterSelectionResponse(
        String status,
        String characterId,
        String selectedCharacterId
) {
}
