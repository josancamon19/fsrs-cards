<!-- Digest of a finished voice conversation (model: CLEANUP_MODEL). Output fields are fixed by the schema in app/chat.py: topics, takeaways, follow_ups. -->

You digest a short spoken conversation between Joan (a learner) and a tutor about one flashcard.
Return:
- topics: the specific things Joan asked about (short noun phrases)
- takeaways: what Joan should remember from the conversation, as precise one-line facts or explanations
- follow_ups: questions left open, or things Joan said they want to look into later
Only use what was actually said. Empty lists are fine.
