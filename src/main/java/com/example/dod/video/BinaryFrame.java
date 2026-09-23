package com.example.dod.video;

public record BinaryFrame<T>(
        T metadata,
        byte[] imageBytes
) {
}
