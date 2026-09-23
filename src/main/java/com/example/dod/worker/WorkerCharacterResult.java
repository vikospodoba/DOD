package com.example.dod.worker;

public record WorkerCharacterResult(
        String status,
        boolean ready,
        String characterId,
        String selectedCharacterId
) {
    public static WorkerCharacterResult unavailable(String characterId) {
        return new WorkerCharacterResult("model_not_ready", false, characterId, "");
    }
}
