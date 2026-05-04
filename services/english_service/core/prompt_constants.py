LEVEL_PROFILES = {
    "beginner": """
Learner profile:
- CEFR: A1-A2
- Use common words and short sentences
- Focus on daily life, family, food, school, work, weather, travel and hobbies
- Good targets: simple present, present continuous, basic past simple, can/can't, articles, prepositions, question forms and subject-verb agreement
""".strip(),
    "intermediate": """
Learner profile:
- CEFR: B1-B2
- Use natural everyday English
- Focus on travel, study, work, communication, health, habits, media, technology and decisions
- Good targets: present perfect, past perfect, future forms, conditionals, modals, passive voice, gerund vs infinitive, phrasal verbs, prepositions, articles and collocations
""".strip(),
    "advanced": """
Learner profile:
- CEFR: C1
- Use sophisticated but natural English
- Focus on academic, professional and formal communication
- Good targets: inversion, reduced clauses, mixed conditionals, complex modals, discourse markers, formal register, collocations, paraphrasing and nuanced meaning
""".strip(),
}

QUIZ_CORE_RULES = """
Rules:
1. Test English knowledge only: grammar, collocation, structure, usage or meaning in English.
2. Each question must have exactly one clearly correct answer.
3. Keep the sentence short, natural and level-appropriate.
4. Use three plausible options; wrong options must be clearly wrong.
5. Return only a valid Python-style list of dictionaries.
""".strip()

QUIZ_OUTPUT_RULES = """
Output format:
- Return only a Python-style list.
- No markdown, no code fences, no extra text.
- Each item must contain exactly these keys: "question", "options", "answer", "explanation".
- "options" must contain exactly 3 strings.
- "answer" must exactly match one option.
- "explanation" must be short and language-based.
""".strip()

QUIZ_VALIDATION_RULES = """
Keep a question only if:
1. It has exactly one correct answer.
2. The English is natural and level-appropriate.
3. The explanation is accurate and language-based.
4. The wrong options are clearly incorrect.
5. It is not repeated, ambiguous or based on general knowledge.
""".strip()

WRITING_FEEDBACK_SCHEMA = {
    "overall_score": 1,
    "grammar_score": 1,
    "vocabulary_score": 1,
    "clarity_score": 1,
    "strengths": ["string", "string"],
    "improvements": ["string", "string"],
    "next_focus": "string",
}