import json


def build_topic_task_prompt(level: str, last_topic: str | None = None) -> str:
    schema = {
        "topic": "string",
        "min_words": 60
    }

    extra_rule = ""
    if last_topic:
        extra_rule = f'\n- Do not generate this topic again: "{last_topic}"'

    return f"""
You are an English writing task generator.

Create ONE different and creative English writing topic for a {level} learner.

Rules:
- The topic must be suitable for {level} level.
- Make it practical, simple, and interesting.
- Try to generate a fresh topic each time.
- Avoid repeating very common topics unless necessary.
{extra_rule}
- Return only valid JSON.
- Do not add explanations.
- Do not use markdown.
- Use this exact schema:

{json.dumps(schema, ensure_ascii=False)}

Example valid output:
{{"topic": "Describe a memorable day with your family", "min_words": 60}}
""".strip()


def build_translation_task_prompt(level: str, last_source_text: str | None = None) -> str:
    schema = {
        "source_text": "Türkçe metin",
        "min_words": 40
    }

    extra_rule = ""
    if last_source_text:
        extra_rule = f'\n- Do not generate this text again: "{last_source_text}"'

    return f"""
You are an English translation exercise generator.

Create ONE different Turkish text for an English translation exercise for a {level} learner.

Rules:
- The text must match {level} level.
- Keep it natural and meaningful.
- Try to generate a fresh text each time.
- Avoid repeating very common texts unless necessary.
{extra_rule}
- Return only valid JSON.
- Do not add explanations.
- Do not use markdown.
- Use this exact schema:

{json.dumps(schema, ensure_ascii=False)}

Example valid output:
{{"source_text": "Geçen hafta arkadaşlarımla sinemaya gittim ve çok eğlendim.", "min_words": 40}}
""".strip()


def build_topic_writing_prompt(level: str, topic: str, user_text: str) -> str:
    return f"""
You are an English teacher.

Level: {level}
Task: topic writing
Topic: {topic}

Student text:
{user_text}

Evaluate:
- grammar
- clarity
- sentence structure
- vocabulary suitability

Be short, clear, and encouraging.
Mention max 2 strengths, max 3 mistakes, and 1 suggestion.

Return in this format:

Overall:
Strengths:
- ...
- ...

Mistakes:
- ...
- ...

Suggestion:
...
""".strip()


def build_translation_writing_prompt(level: str, source_text: str, user_text: str) -> str:
    return f"""
You are an English teacher.

Level: {level}
Task: translation writing

Original Turkish text:
{source_text}

Student translation:
{user_text}

Evaluate:
- meaning accuracy
- grammar
- natural English
- clarity

Do not require word-for-word translation.
Be short, clear, and encouraging.
Mention max 2 strengths, max 3 mistakes, and 1 suggestion.

Return in this format:

Overall:
Strengths:
- ...
- ...

Mistakes:
- ...
- ...

Suggestion:
...
""".strip()


def build_quiz_prompt(
    level: str,
    question_count: int = 5,
    previous_questions: list[str] | None = None
) -> str:
    level_profiles = {
        "beginner": """
Target learner profile:
- CEFR: A1-A2
- Use very common vocabulary and short sentences
- Focus on everyday English
- Suitable topics: daily routine, food, family, school, work, weather, travel, hobbies
- Suitable grammar:
  - simple present
  - present continuous
  - basic past simple
  - can / can't
  - basic prepositions
  - articles
  - subject-verb agreement
  - basic question forms
- Avoid:
  - advanced abstract vocabulary
  - inversion
  - reduced clauses
  - mixed conditionals
  - complex passive structures
""",
        "intermediate": """
Target learner profile:
- CEFR: B1-B2
- Use natural but not highly literary English
- Suitable topics: travel, study, work, communication, health, habits, media, technology, daily decisions
- Suitable grammar and usage:
  - present perfect
  - past perfect
  - future forms
  - conditionals
  - modals
  - passive voice
  - gerund vs infinitive
  - phrasal verbs
  - prepositions
  - articles
  - collocations
  - sentence meaning
- Avoid:
  - overly academic wording
  - highly obscure idioms
  - extremely rare vocabulary
  - too many nearly identical tense questions
""",
        "advanced": """
Target learner profile:
- CEFR: C1
- Use sophisticated but still natural English
- Suitable topics: academic communication, professional settings, public discourse, social issues, argumentation, policy, abstract reasoning, formal writing
- Suitable grammar and usage:
  - advanced tense contrasts
  - inversion
  - reduced clauses
  - mixed conditionals
  - complex modals
  - discourse markers
  - formal register
  - collocations
  - paraphrasing
  - nuanced meaning differences
  - advanced sentence structure
- Avoid:
  - trivia knowledge
  - very culture-specific references
  - obscure archaic language
  - more than one plausible correct answer
""",
    }

    previous_block = ""
    if previous_questions:
        joined = "\n".join(f"- {q}" for q in previous_questions[-20:])
        previous_block = f"""
Previously used questions:
{joined}

Critical repetition rule:
- Do NOT repeat any of the previous questions
- Do NOT produce questions that are very similar in grammar pattern, wording, or answer logic
- Do NOT reuse well-worn patterns like:
  - "By the time I arrived..."
  - "By next year, I..."
  - "If I won the lottery..."
  - "I wish I..."
unless absolutely necessary
"""
    STRICT_QUALITY_RULES = """  
    CRITICAL QUALITY RULES:

    1. NO LOGIC-BASED QUESTIONS
    Do NOT create questions that can be answered using general logic or context alone.
    Each question MUST require knowledge of English:
    - grammar
    - collocation
    - structure
    - usage

    If a learner can guess the answer without knowing English rules, the question is invalid.

    2. SINGLE CORRECT ANSWER ONLY
    If more than one option could reasonably be correct, DO NOT include the question.
    Even slight ambiguity is not allowed.

    3. SHORT AND CLEAR SENTENCES
    Avoid overly long academic sentences.
    Prefer:
    - one clear sentence
    - one clear target

    4. EXPLANATION MUST BE LANGUAGE-BASED
    Explanation must explain a language rule.

    Do NOT explain using:
    - context logic
    - general meaning only
    """
    return f"""
    {STRICT_QUALITY_RULES}
You are an expert English assessment designer.


Your job is to create {question_count} high-quality multiple-choice English quiz questions for a {level} learner.

{level_profiles.get(level, level_profiles["intermediate"])}

Global goals:
- The quiz must feel varied, fresh, fair, and educational
- Questions must be reliable enough for language practice
- Avoid repetitive grammar traps and recycled textbook examples
- Prefer natural English over robotic exam language
- The set must include a balanced variety of question types

Mandatory distribution across the full quiz set:
- 1 grammar/tense question
- 1 vocabulary/collocation question
- 1 structure/usage question
- 1 meaning/paraphrase question
- 1 modal/preposition/article/register question

If needed, combine categories carefully, but keep the set varied.

Strict output format:
- Return only a valid Python-style list of dictionaries
- No markdown
- No code fences
- No explanations outside the list
- No introductory or closing text
- Each dictionary must contain exactly these keys:
  "question", "options", "answer", "explanation"

Required structure for each item:
- "question": string
- "options": list of exactly 3 strings
- "answer": exactly one of the 3 options
- "explanation": short, accurate, helpful string

Critical quality rules:
1. Every question must have exactly ONE clearly correct answer.
2. Do NOT create ambiguous questions.
3. Do NOT create questions where two options could both reasonably be correct.
4. Do NOT create explanation text unless it is linguistically accurate.
5. Do NOT create distractors that are nonsense unless the level is beginner and the contrast is intentional.
6. Distractors should be plausible but still clearly wrong.
7. The correct answer must match standard natural English usage.
8. Avoid awkward or unnatural sentence stems.
9. Avoid trick questions.
10. Do not test general knowledge; test English.

Answer quality rules:
- The correct answer must be unambiguously the best answer
- If an option could also be accepted in some reasonable context, do not use that question
- Avoid context-dependent ambiguity
- Avoid semantic overreach in paraphrase questions
- Avoid stronger/weaker wording mismatches unless the contrast is explicitly the point of the question

Explanation rules:
- Keep explanations short
- Explanations must be correct
- Do not use incorrect grammar terminology
- Do not say present simple is future simple
- Do not mislabel conditionals
- Do not invent rules
- Explain why the correct answer is correct, not just that it is correct

Distractor rules:
- Distractors must be grammatically plausible where appropriate
- Distractors must not accidentally become correct through alternate interpretation
- Avoid distractors that differ only by punctuation or formatting
- Avoid distractors that are too obviously wrong unless learner level is beginner

Variation rules:
- Avoid repeating the same stem pattern
- Avoid repeating the same grammar target more than once unless necessary
- Avoid multiple questions built around conditionals unless one is genuinely distinct
- Avoid multiple questions built around past perfect unless one is genuinely distinct
- Avoid multiple "fill in the blank" questions with almost identical logic
- At least one question should feel meaning-based, not purely form-based
- At least one question should feel usage-based, not purely tense-based

Paraphrase/meaning rules:
- Only create a paraphrase/meaning question if one option is truly closest in meaning
- Do not create misleading paraphrases
- Do not make the correct answer stronger or broader than the original meaning unless explicitly intended
- Keep meaning equivalence realistic, not absolute perfection

Advanced-level rules:
- For advanced level, include at least 2 of these somewhere in the set:
  - inversion
  - reduced clause
  - collocation
  - paraphrase
  - formal register
  - nuanced meaning
- But still preserve one clear answer only

Beginner-level rules:
- Keep wording short and transparent
- Avoid confusing metalanguage
- Prefer everyday contexts

Intermediate-level rules:
- Mix common grammar with practical usage
- Include at least one item that checks meaning or collocation, not only tense

{previous_block}

Before finalizing internally, silently check each question:
- Is there exactly one correct answer?
- Is the explanation truly correct?
- Is the sentence natural?
- Is this too similar to a previous question?
- Is this too similar to another question in the same set?
- Is this appropriate for {level} level?

If any question fails, replace it before returning the final result.

Return only the Python-style list of dictionaries.
""".strip()

def build_quiz_validation_prompt(questions: list[dict], level: str) -> str:
    VALIDATOR_EXTRA_RULES = """
CRITICAL REJECTION RULES:

Reject the question if:
- It can be answered using general reasoning instead of English knowledge
- It relies only on positive/negative context clues
- More than one option could be correct
- The distinction between options is unclear
"""
    return f"""
    {VALIDATOR_EXTRA_RULES}
You are a strict English language assessment reviewer.

Your task is to review a set of multiple-choice English quiz questions for a {level} learner.

You must keep only questions that meet ALL requirements below.

Validation requirements:
1. The question must be grammatically correct.
2. The sentence must sound natural in English.
3. There must be exactly one clearly correct answer.
4. The other two options must be clearly incorrect, but still plausible where appropriate.
5. The explanation must be accurate and must not misuse grammar terminology.
6. The question must be suitable for {level} level.
7. The question must not be too similar to another question in the set.
8. The question must not be repetitive or built on an overused pattern.
9. The question must not be misleading, ambiguous, or context-dependent in a way that makes multiple answers possible.
10. The question must test English, not background knowledge.

Special rejection conditions:
- Reject any question with two possibly acceptable answers
- Reject any question whose explanation is partially or fully wrong
- Reject any question with awkward, unnatural, or artificial English
- Reject any question that overstates paraphrase equivalence
- Reject any question that uses the wrong grammar label
- Reject any question that feels like a recycled generic textbook pattern if the set already contains similar ones

Important behavior:
- If a question is valid, keep it exactly as it is
- If a question is invalid, remove it entirely
- Do not rewrite invalid questions
- Do not add new questions
- Do not add comments
- Return only the valid questions

Output format rules:
- Return only a valid Python-style list of dictionaries
- No markdown
- No extra text
- Each dictionary must contain exactly:
  "question", "options", "answer", "explanation"

Questions to validate:
{questions}
""".strip()