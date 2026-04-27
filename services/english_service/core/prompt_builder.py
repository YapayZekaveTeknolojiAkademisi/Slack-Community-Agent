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


def build_topic_writing_prompt(level, topic, user_text):
    return f"""
You are a strict English writing evaluator.

Evaluate the student's writing.

Level: {level}
Topic: {topic}

Student text:
{user_text}

Score these from 1-10:
- overall_score
- grammar_score
- vocabulary_score
- clarity_score

Return ONLY valid JSON.
No markdown.
No comments.
No prose.
No explanations outside JSON.

Use EXACTLY this schema:

{{
"overall_score": 7,
"grammar_score": 7,
"vocabulary_score": 6,
"clarity_score": 7,
"strengths": [
"Clear sentence structure",
"Good basic vocabulary"
],
"improvements": [
"Improve article usage",
"Use more varied vocabulary"
],
"next_focus":"Practice sentence variety"
}}

Return JSON only.
""".strip()


def build_translation_writing_prompt(level, source_text, user_text):
    return f"""
You are a strict English translation evaluator.

Evaluate the student's translation.

Level: {level}

Original Turkish text:
{source_text}

Student translation:
{user_text}

Score these from 1-10:
- overall_score
- grammar_score
- vocabulary_score
- clarity_score

Evaluate:
- meaning accuracy
- grammar
- natural English

Return ONLY valid JSON.
No markdown.
No comments.
No prose.

Use EXACTLY this schema:

{{
"overall_score":7,
"grammar_score":7,
"vocabulary_score":7,
"clarity_score":7,
"strengths":[
"Good meaning accuracy",
"Natural sentence structure"
],
"improvements":[
"Stay closer to source meaning",
"Improve article usage"
],
"next_focus":"Practice faithful translation"
}}

Return JSON only.
""".strip()


def build_quiz_prompt(
    level: str,
    question_count: int = 5,
    previous_questions: list[str] | None = None,
    target_types: list[str] | None = None,
) -> str:
    level_profiles = {
        "beginner": """
Target learner profile:
- CEFR: A1-A2
- Use very common vocabulary and short sentences.
- Focus on everyday English.
- Suitable topics: daily routine, food, family, school, work, weather, travel, hobbies.
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
- Use natural but not highly literary English.
- Suitable topics: travel, study, work, communication, health, habits, media, technology, daily decisions.
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
- Use sophisticated but natural English.
- Focus on academic, professional and formal communication.
- The question must test genuinely advanced language control, not just long sentences.

Good advanced targets:
- inversion after negative or restrictive adverbials
- inverted conditionals
- mixed conditionals
- reduced relative clauses
- participle clauses
- formal register
- hedging and cautious academic language
- discourse markers
- advanced collocations
- nuanced meaning differences
- parallel structure
- concessive clauses
- sentence transformation
- paraphrasing with meaning preservation

Avoid for advanced:
- basic present perfect questions
- basic simple past questions
- basic simple present questions
- basic passive voice questions
- basic subject-verb agreement
- basic verb form questions like "managed to ___"
- simple vocabulary synonym questions
- questions that are only advanced because the sentence is long
- generic climate-change or company-policy examples unless the target structure is genuinely advanced
""",
    }

    previous_block = ""
    if previous_questions:
        joined = "\n".join(f"- {q}" for q in previous_questions[-20:])
        previous_block = f"""
Previously used questions:
{joined}

Critical repetition rule:
- Do NOT repeat any of the previous questions.
- Do NOT produce questions that are very similar in grammar pattern, wording, or answer logic.
- Do NOT reuse well-worn patterns like:
  - "By the time I arrived..."
  - "By next year, I..."
  - "If I won the lottery..."
  - "I wish I..."
unless absolutely necessary.
"""

    target_types = target_types or []
    target_type_block = ""
    if target_types:
        joined_types = "\n".join(f"- {item}" for item in target_types)
        target_type_block = f"""
Python-controlled target types:
Use these target types across the quiz:
{joined_types}

Important:
- Every question MUST include a "target_type" value.
- The "target_type" value MUST be exactly one of the target types above.
- Try to use each target type at most once.
- The target_type must describe the actual language point tested by the blank or answer choice.
- Do not label a basic verb-form question as "formal register", "advanced collocations", or "reduced clause".
"""

    advanced_extra_rules = ""
    if level == "advanced":
        advanced_extra_rules = """
ADVANCED-LEVEL STRICT RULES:

Advanced questions must NOT simply be intermediate questions with longer wording.

Reject these advanced question types:
- simple present choice: indicate / indicates / indicated
- simple past choice: contributed / has contributed / was contributed
- basic present perfect choice: has had / had / is having
- basic passive choice: reviewed / reviewing / to review
- basic verb pattern choice: managed to ___, had to ___, intended to ___
- basic synonym choice with obvious options
- any question where the explanation says "simple past", "simple present", or "present perfect" as the main tested point

For advanced level, each question must test at least one of these:
- inversion
- inverted conditional
- mixed conditional
- reduced relative clause
- participle clause
- formal register choice
- nuanced collocation
- discourse marker
- concessive structure
- parallel structure
- advanced paraphrase
- subtle meaning difference

Target-type accuracy rules for advanced:
- "inversion" must involve changed word order after a negative/restrictive adverbial, or an inverted conditional.
- "advanced conditionals" must involve third conditional, mixed conditional, or inverted conditional. Do not use ordinary first or second conditional.
- "formal register" must test formal wording, register, hedging, or academic style. Do not use it for basic base-verb selection.
- "advanced collocations" must test a real collocation or word partnership, not simple grammar.
- "nuanced meaning" must test a subtle meaning difference, not a basic synonym.
- "relative clauses" must test relative clause structure, reduced relative clauses, or participle clauses.

Good advanced examples:
[
  {
    "question": "Only after the evidence had been reviewed ___ the committee revise its recommendation.",
    "options": ["did", "had", "was"],
    "answer": "did",
    "explanation": "After 'only after' is fronted, subject-auxiliary inversion is required.",
    "target_type": "inversion"
  },
  {
    "question": "Had the risks been assessed earlier, the project ___ such severe delays.",
    "options": ["would not have faced", "will not face", "does not face"],
    "answer": "would not have faced",
    "explanation": "This is an inverted third conditional: 'Had the risks been assessed...' means 'If the risks had been assessed...'.",
    "target_type": "advanced conditionals"
  },
  {
    "question": "The proposal, ___ with sufficient evidence, would have been more persuasive.",
    "options": ["supported", "supporting", "was supported"],
    "answer": "supported",
    "explanation": "A reduced passive relative clause uses the past participle: 'proposal supported with evidence'.",
    "target_type": "relative clauses"
  }
]

Bad advanced examples:
[
  {
    "question": "The results of the study ___ the need for further research.",
    "options": ["indicate", "has indicated", "had indicated"],
    "answer": "indicate",
    "explanation": "The verb is in the simple present tense.",
    "target_type": "formal register"
  },
  {
    "question": "The team ___ to their defeat.",
    "options": ["contributed", "has contributed", "was contributed"],
    "answer": "contributed",
    "explanation": "Use simple past for a completed action.",
    "target_type": "advanced collocations"
  },
  {
    "question": "The company has managed to ___ its market share.",
    "options": ["increase", "to increase", "increasing"],
    "answer": "increase",
    "explanation": "After 'managed to', use the base verb.",
    "target_type": "formal register"
  }
]

Do not generate questions like the bad examples.
"""

    strict_quality_rules = """
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

5. EXPLANATION MUST MATCH THE REAL GRAMMAR POINT
Do not misuse grammar terminology.
Do not call a past simple passive answer "past perfect".
Do not call a second conditional a past situation.
Do not say the answer is "to write" when the actual answer is "write".
Do not label a basic verb-form question as an advanced structure.
"""

    return f"""
{strict_quality_rules}

You are an expert English assessment designer.

Your job is to create {question_count} high-quality multiple-choice English quiz questions for a {level} learner.

{level_profiles.get(level, level_profiles["intermediate"])}

{target_type_block}

{advanced_extra_rules}

Global goals:
- The quiz must feel varied, fresh, fair, and educational.
- Questions must be reliable enough for language practice.
- Avoid repetitive grammar traps and recycled textbook examples.
- Prefer natural English over robotic exam language.
- The set must include a balanced variety of question types.

Strict output format:
- Return only a valid Python-style list of dictionaries.
- No markdown.
- No code fences.
- No explanations outside the list.
- No introductory or closing text.
- Each dictionary must contain exactly these keys:
  "question", "options", "answer", "explanation", "target_type"

Required structure for each item:
- "question": string
- "options": list of exactly 3 strings
- "answer": exactly one of the 3 options
- "explanation": short, accurate, helpful string
- "target_type": exactly one of the Python-controlled target types

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
11. The explanation must match the actual answer, not a different form.
12. The target_type must match the real language point tested.

Answer quality rules:
- The correct answer must be unambiguously the best answer.
- If an option could also be accepted in some reasonable context, do not use that question.
- Avoid context-dependent ambiguity.
- Avoid semantic overreach in paraphrase questions.
- Avoid stronger/weaker wording mismatches unless the contrast is explicitly the point.
- Reject modal verb questions unless context makes only one answer possible.
- Avoid questions where both affirmative and negative forms could fit.
- Do not generate items like:
  I ___ play tennis
  (can / can't / may)
  because more than one answer may be plausible.

Explanation rules:
- Keep explanations short.
- Explanations must be correct.
- Do not use incorrect grammar terminology.
- Do not say present simple is future simple.
- Do not mislabel conditionals.
- Do not call past simple passive "past perfect".
- Do not invent rules.
- Explain why the correct answer is correct, not just that it is correct.
- If the blank already contains "to ___", explain that the base verb is required after "to".

Distractor rules:
- Distractors must be grammatically plausible where appropriate.
- Distractors must not accidentally become correct through alternate interpretation.
- Avoid distractors that differ only by punctuation or formatting.
- Avoid distractors that are too obviously wrong unless learner level is beginner.

Variation rules:
- Avoid repeating the same stem pattern.
- Avoid repeating the same grammar target more than once unless necessary.
- Avoid multiple questions built around conditionals unless one is genuinely distinct.
- Avoid multiple questions built around past perfect unless one is genuinely distinct.
- Avoid multiple fill-in-the-blank questions with almost identical logic.
- At least one question should feel meaning-based, not purely form-based.
- At least one question should feel usage-based, not purely tense-based.

Paraphrase/meaning rules:
- Only create a paraphrase/meaning question if one option is truly closest in meaning.
- Do not create misleading paraphrases.
- Do not make the correct answer stronger or broader than the original meaning unless explicitly intended.
- Keep meaning equivalence realistic, not absolute perfection.

Beginner-level rules:
- Keep wording short and transparent.
- Avoid confusing metalanguage.
- Prefer everyday contexts.

Intermediate-level rules:
- Mix common grammar with practical usage.
- Include at least one item that checks meaning or collocation, not only tense.

Advanced-level final check:
- If level is advanced, reject any question whose main explanation is only simple present, simple past, basic present perfect, basic passive, or basic verb pattern.
- If level is advanced, the tested point must be genuinely C1-level.
- If level is advanced, the sentence must not merely be long; the tested structure must be advanced.

{previous_block}

Before finalizing internally, silently check each question:
- Is there exactly one correct answer?
- Is the explanation truly correct?
- Does the explanation match the answer?
- Is the sentence natural?
- Is this too similar to a previous question?
- Is this too similar to another question in the same set?
- Is this appropriate for {level} level?
- Is target_type exactly one of the allowed target types?
- For advanced level, is the tested structure truly advanced?

Example output format:
[
  {{
    "question": "Only after the evidence had been reviewed ___ the committee revise its recommendation.",
    "options": ["did", "had", "was"],
    "answer": "did",
    "explanation": "After 'only after' is fronted, subject-auxiliary inversion is required.",
    "target_type": "inversion"
  }}
]

Return only the Python-style list of dictionaries.
""".strip()


def build_quiz_validation_prompt(questions: list[dict], level: str) -> str:
    validator_extra_rules = """
CRITICAL REJECTION RULES:

Reject the question if:
- It can be answered using general reasoning instead of English knowledge.
- It relies only on positive/negative context clues.
- More than one option could be correct.
- The distinction between options is unclear.
- The explanation uses the wrong grammar label.
- The explanation does not match the actual answer.
- The target_type does not match the real language point tested.
"""

    advanced_validator_rules = ""
    if level == "advanced":
        advanced_validator_rules = """
ADVANCED VALIDATION RULES:

For advanced level, reject the question if the main tested point is only:
- simple present
- simple past
- basic present perfect
- basic passive voice
- basic subject-verb agreement
- basic verb pattern such as "managed to + verb", "had to + verb", or "intended to + verb"
- basic synonym recognition

For advanced level, keep the question only if it tests at least one genuinely advanced point:
- inversion
- inverted conditional
- mixed conditional
- reduced relative clause
- participle clause
- formal register
- hedging or cautious academic language
- discourse marker
- concessive structure
- parallel structure
- advanced collocation
- nuanced meaning difference
- advanced paraphrase

Reject if:
- The sentence is long but the actual blank only tests a basic verb form.
- target_type says "formal register" but the question only tests a base verb.
- target_type says "advanced collocations" but the question only tests tense.
- target_type says "relative clauses" but the blank does not test relative clause structure.
- target_type says "nuanced meaning" but the options are obvious basic synonyms.
- The explanation mentions an advanced label but explains a basic grammar rule.
"""

    return f"""
{validator_extra_rules}

{advanced_validator_rules}

You are a strict English language assessment reviewer.

Your task is to review a set of multiple-choice English quiz questions for a {level} learner.

You must keep only questions that meet ALL requirements below.

Validation requirements:
1. The question must be grammatically correct.
2. The sentence must sound natural in English.
3. There must be exactly one clearly correct answer.
4. The other two options must be clearly incorrect, but still plausible where appropriate.
5. The explanation must be accurate and must not misuse grammar terminology.
6. The explanation must match the actual answer.
7. The question must be suitable for {level} level.
8. The question must not be too similar to another question in the set.
9. The question must not be repetitive or built on an overused pattern.
10. The question must not be misleading, ambiguous, or context-dependent in a way that makes multiple answers possible.
11. The question must test English, not background knowledge.
12. The target_type must be present and accurate.

Special rejection conditions:
- Reject any question with two possibly acceptable answers.
- Reject any question whose explanation is partially or fully wrong.
- Reject any question with awkward, unnatural, or artificial English.
- Reject any question that overstates paraphrase equivalence.
- Reject any question that uses the wrong grammar label.
- Reject any question that feels like a recycled generic textbook pattern if the set already contains similar ones.
- Reject any modal verb question where positive and negative forms could both fit.
- Reject fill-in-the-blank questions with insufficient context to force one answer.
- Reject questions where can / can't / may or similar modal choices could all be plausible.
- Reject any question without target_type.
- Reject any question where target_type is unrelated to the tested language point.

Important behavior:
- If a question is valid, keep it exactly as it is.
- If a question is invalid, remove it entirely.
- Do not rewrite invalid questions.
- Do not add new questions.
- Do not add comments.
- Return only the valid questions.

Output format rules:
- Return only a valid Python-style list of dictionaries.
- No markdown.
- No extra text.
- Each dictionary must contain exactly:
  "question", "options", "answer", "explanation", "target_type"

Questions to validate:
{questions}
""".strip()