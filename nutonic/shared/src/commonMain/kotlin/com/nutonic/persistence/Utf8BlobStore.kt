package com.nutonic.persistence

/** Small UTF-8 blob persistence for local JSON (`IMP-083`, `rules/13`). */
interface Utf8BlobStore {
    suspend fun load(): String?

    suspend fun save(text: String)
}

class MemoryUtf8BlobStore : Utf8BlobStore {
    private var snapshot: String? = null

    override suspend fun load(): String? = snapshot

    override suspend fun save(text: String) {
        snapshot = text
    }
}

expect fun createLocalLeaderboardBlobStore(): Utf8BlobStore

/** Guess-record POST outbox (`GuessRecordOutboxRepository`). */
expect fun createGuessSyncOutboxBlobStore(): Utf8BlobStore

/** PRO on-device VLM model manifest and cache metadata. Model binaries are never stored in git. */
expect fun createProVlmModelBlobStore(): Utf8BlobStore
