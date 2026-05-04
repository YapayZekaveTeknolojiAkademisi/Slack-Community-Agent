import ast
import random
import re

from services.english_service.models import Session
from services.english_service.core.level_config import (
    PREVIOUS_QUIZ_LIMIT,
    QUIZ_SIMILARITY_THRESHOLD,
    get_random_quiz_question_types,
)
from services.english_service.core.metrics import Metrics
from services.english_service.core.prompt_builder import (
    build_quiz_prompt,
    build_quiz_validation_prompt,
)
from services.english_service.llm.client import BaseLLMClient, GroqLLMClient
from services.english_service.core.semantic_similarity import is_semantically_repeated
from services.english_service.logger import _logger


class QuizMode:
    ALLOWED_TARGET_TYPES = {
        "beginner": {
            "present simple",
            "present continuous",
            "articles",
            "basic prepositions",
            "basic vocabulary",
            "subject verb agreement",
        },
        "intermediate": {
            "present perfect",
            "conditionals",
            "modals",
            "passive voice",
            "collocations",
            "gerund infinitive",
        },
        "advanced": {
            "inversion",
            "advanced conditionals",
            "formal register",
            "advanced collocations",
            "nuanced meaning",
            "relative clauses",
        },
    }

    MIN_VALID_QUESTIONS = 5
    GENERATED_QUESTION_COUNT = 10

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        validator_client: BaseLLMClient | None = None,
    ):
        self.llm = llm_client or GroqLLMClient(
            temperature=0.7,
            system_message="You generate varied and level-appropriate English quiz questions.",
        )
        self.validator_llm = validator_client or GroqLLMClient(
            temperature=0.2,
            system_message="You carefully validate English quiz questions and remove wrong or ambiguous items.",
        )

    def start_quiz(self, session: Session):
        self._ensure_quiz_state(session)

        previous_questions = session.data.get("previous_quiz_questions", [])
        question_types = get_random_quiz_question_types(
            session.level,
            count=self.MIN_VALID_QUESTIONS,
        )
        session.data["used_quiz_question_types"] = question_types

        prompt = build_quiz_prompt(
            level=session.level,
            question_count=self.GENERATED_QUESTION_COUNT,
            previous_questions=previous_questions,
            target_types=question_types,
        )

        try:
            llm_response = self.llm.generate(prompt)
        except Exception as exc:
            Metrics.inc("quiz_validation_failures")
            _logger.warning(
                "Quiz generation failed. Falling back to fallback quiz. error=%s",
                exc,
            )
            return self._start_fallback_quiz(session)

        _logger.debug("Quiz raw response: %s", llm_response)

        questions = self._parse_questions_response(llm_response)
        if questions is None:
            Metrics.inc("json_parse_failures")
            _logger.warning("Quiz response parsing failed. Falling back to fallback quiz.")
            return self._start_fallback_quiz(session)

        validated_questions = self._basic_validate_questions(
            questions=questions,
            previous_questions=previous_questions,
            level=session.level,
        )

        _logger.debug(
            "Quiz generated=%s basic_valid=%s",
            len(questions),
            len(validated_questions),
        )

        if not validated_questions:
            Metrics.inc("quiz_validation_failures")
            _logger.warning("Quiz basic validation returned no valid questions.")
            return self._start_fallback_quiz(session)

        llm_validated_questions = self._llm_validate_questions(
            questions=validated_questions,
            level=session.level,
        )

        if llm_validated_questions is None:
            Metrics.inc("quiz_validation_failures")
            _logger.warning("Quiz LLM validation failed. Falling back to fallback quiz.")
            return self._start_fallback_quiz(session)

        validated_questions = self._basic_validate_questions(
            questions=llm_validated_questions,
            previous_questions=previous_questions,
            level=session.level,
        )

        _logger.debug(
            "Quiz llm_validated=%s final_valid=%s",
            len(llm_validated_questions),
            len(validated_questions),
        )

        if len(validated_questions) < self.MIN_VALID_QUESTIONS:
            validated_questions = self._complete_with_fallback_questions(
                questions=validated_questions,
                session=session,
                previous_questions=previous_questions,
            )

            _logger.debug(
                "Quiz completed with fallback. final_count=%s",
                len(validated_questions),
            )

        if len(validated_questions) < self.MIN_VALID_QUESTIONS:
            Metrics.inc("quiz_validation_failures")
            _logger.warning("Quiz could not be completed with fallback questions.")
            return self._start_fallback_quiz(session)

        selected_questions = self._select_balanced_questions(
            questions=validated_questions,
            count=self.MIN_VALID_QUESTIONS,
            level=session.level,
        )

        session.data["quiz_questions"] = selected_questions
        session.data["current_index"] = 0
        session.step = "waiting_quiz_answer"

        self._store_previous_questions(session, selected_questions)

        return self._format_current_question(session)

    def submit_answer(self, session: Session, selected_value: str):
        questions = session.data.get("quiz_questions", [])
        current_index = session.data.get("current_index", 0)

        if current_index >= len(questions):
            return self.finish_quiz(session)

        current_question = questions[current_index]

        try:
            options = current_question["options"]
            correct_answer = current_question["answer"]
        except KeyError:
            return {
                "type": "quiz_error",
                "message": "This quiz question is invalid. Please start a new quiz.",
            }

        try:
            selected_index = int(selected_value) - 1
            if selected_index < 0 or selected_index >= len(options):
                raise ValueError("Selected option index is out of range.")
            selected_option = options[selected_index]
        except Exception:
            return {
                "type": "quiz_feedback",
                "message": "Please choose a valid option number.",
            }

        explanation = current_question.get("explanation", "")

        if selected_option == correct_answer:
            feedback = (
                "Correct ✅\n"
                f"Explanation: {explanation}"
            )
        else:
            feedback = (
                "Wrong ❌\n"
                f"Correct answer: {correct_answer}\n"
                f"Explanation: {explanation}"
            )

        session.data["current_index"] = current_index + 1
        next_question = self._format_current_question(session)

        return {
            "type": "quiz_feedback",
            "message": feedback,
            "next": next_question,
        }

    def _format_current_question(self, session: Session):
        questions = session.data.get("quiz_questions", [])
        current_index = session.data.get("current_index", 0)

        if current_index >= len(questions):
            return self.finish_quiz(session)

        question = questions[current_index]

        options_text = "\n".join(
            f"{idx + 1}. {option}"
            for idx, option in enumerate(question["options"])
        )

        return {
            "type": "quiz_question",
            "message": (
                f"Question {current_index + 1}/{len(questions)}\n"
                f"{question['question']}\n"
                f"{options_text}"
            ),
        }

    def finish_quiz(self, session: Session):
        session.step = "quiz_finished"
        return {
            "type": "quiz_result",
            "message": "Quiz finished.",
        }

    def _parse_questions_response(self, raw_response: str):
        if not isinstance(raw_response, str):
            return None

        cleaned = raw_response.strip()

        try:
            return ast.literal_eval(cleaned)
        except Exception:
            pass

        fenced = re.search(
            r"```(?:python|json)?\s*(\[.*\])\s*```",
            cleaned,
            re.DOTALL,
        )
        if fenced:
            try:
                return ast.literal_eval(fenced.group(1))
            except Exception:
                pass

        list_match = re.search(
            r"\[.*\]",
            cleaned,
            re.DOTALL,
        )
        if list_match:
            try:
                return ast.literal_eval(list_match.group(0))
            except Exception:
                pass

        return None

    def _basic_validate_questions(
        self,
        questions,
        previous_questions: list[str] | None = None,
        level: str = "intermediate",
    ):
        if not isinstance(questions, list):
            return []

        previous_questions = previous_questions or []
        previous_lower = {
            q.strip().lower()
            for q in previous_questions
            if isinstance(q, str)
        }

        validated = []
        seen_current = set()

        repeated_patterns = [
            "by the time i arrived",
            "by next year, i",
            "if i won the lottery",
            "she is not used to",
            "i wish i",
        ]

        allowed_target_types = self.ALLOWED_TARGET_TYPES.get(
            level,
            self.ALLOWED_TARGET_TYPES["intermediate"],
        )

        for q in questions:
            if not isinstance(q, dict):
                continue

            question = q.get("question")
            options = q.get("options")
            answer = q.get("answer")
            explanation = q.get("explanation", "")
            target_type = q.get("target_type")

            if not isinstance(question, str) or not question.strip():
                continue

            cleaned_question = question.strip()
            lowered_question = cleaned_question.lower()

            if lowered_question in previous_lower:
                continue

            if lowered_question in seen_current:
                continue

            if is_semantically_repeated(
                cleaned_question,
                list(previous_lower) + list(seen_current),
                QUIZ_SIMILARITY_THRESHOLD,
            ):
                continue

            if any(pattern in lowered_question for pattern in repeated_patterns):
                continue

            if not isinstance(options, list) or len(options) != 3:
                continue

            cleaned_options = []
            option_set = set()
            duplicate_option = False

            for opt in options:
                if not isinstance(opt, str) or not opt.strip():
                    duplicate_option = True
                    break

                cleaned_opt = opt.strip()
                lowered_opt = cleaned_opt.lower()

                if lowered_opt in option_set:
                    duplicate_option = True
                    break

                option_set.add(lowered_opt)
                cleaned_options.append(cleaned_opt)

            if duplicate_option:
                continue

            if not isinstance(answer, str) or not answer.strip():
                continue

            cleaned_answer = answer.strip()
            lowered_answer = cleaned_answer.lower()
            lowered_options = [opt.lower() for opt in cleaned_options]

            if lowered_answer not in lowered_options:
                continue

            canonical_answer = cleaned_options[lowered_options.index(lowered_answer)]

            if not isinstance(explanation, str) or not explanation.strip():
                continue

            cleaned_explanation = explanation.strip()

            if self._has_explanation_contradiction(
                question=cleaned_question,
                answer=canonical_answer,
                explanation=cleaned_explanation,
            ):
                Metrics.inc("quiz_validation_failures")
                _logger.debug(
                    "Quiz question rejected due to explanation contradiction. question=%s answer=%s explanation=%s",
                    cleaned_question,
                    canonical_answer,
                    cleaned_explanation,
                )
                continue

            if not isinstance(target_type, str) or not target_type.strip():
                continue

            cleaned_target_type = target_type.strip().lower()

            if cleaned_target_type not in allowed_target_types:
                continue

            if len(cleaned_question) < 10:
                continue

            validated.append({
                "question": cleaned_question,
                "options": cleaned_options,
                "answer": canonical_answer,
                "explanation": cleaned_explanation,
                "target_type": cleaned_target_type,
            })

            seen_current.add(lowered_question)

        return validated

    def _llm_validate_questions(self, questions: list[dict], level: str):
        prompt = build_quiz_validation_prompt(questions, level)

        try:
            response = self.validator_llm.generate(prompt)
        except Exception as exc:
            Metrics.inc("quiz_validation_failures")
            _logger.warning(
                "Quiz LLM validation request failed. Using basic-validated questions. error=%s",
                exc,
            )
            return questions

        _logger.debug("Quiz validation response: %s", response)

        validated_questions = self._parse_questions_response(response)

        if validated_questions is None:
            Metrics.inc("json_parse_failures")
            _logger.warning("Quiz validation response parsing failed.")
            return None

        if not isinstance(validated_questions, list):
            Metrics.inc("quiz_validation_failures")
            _logger.warning(
                "Quiz validation response is not a list. response_type=%s",
                type(validated_questions).__name__,
            )
            return None

        return validated_questions

    def _has_explanation_contradiction(
        self,
        question: str,
        answer: str,
        explanation: str,
    ) -> bool:
        question_l = question.lower()
        answer_l = answer.lower().strip()
        explanation_l = explanation.lower()

        forbidden_by_answer = {
            "was awarded": ["past perfect", "present perfect", "future"],
            "was directed": ["past perfect", "present perfect", "future"],
            "was made": ["past perfect", "present perfect", "future"],
            "was built": ["past perfect", "present perfect", "future"],
            "was written": ["past perfect", "present perfect", "future"],
            "were reviewed": ["past perfect", "present perfect", "future"],
            "is being made worse": ["past perfect", "future"],
            "has worked": ["past simple", "past perfect", "future"],
            "has been working": ["past simple", "past perfect"],
            "had been finished": ["present perfect", "past simple", "future"],
            "had been completed": ["present perfect", "past simple", "future"],
            "had been listed": ["present perfect", "past simple", "future"],
        }

        for known_answer, forbidden_terms in forbidden_by_answer.items():
            if answer_l == known_answer:
                if any(term in explanation_l for term in forbidden_terms):
                    return True

        if answer_l == "would":
            if "future intention" in explanation_l:
                return True

            if "future plan" in explanation_l:
                return True

            if "will" in explanation_l and "second conditional" not in explanation_l:
                return True

        if answer_l in {"have", "has"}:
            if "present perfect" in explanation_l:
                return True

        if question_l.strip().startswith("under no circumstances"):
            modal_options = {"will", "would", "can", "could", "should", "may", "might"}

            if answer_l in modal_options:
                return True

        base_verb_answers = {
            "write",
            "improve",
            "go",
            "make",
            "take",
            "finish",
            "implement",
            "check",
        }

        if answer_l in base_verb_answers:
            if "to infinitive" in explanation_l and f"to {answer_l}" not in explanation_l:
                return True

            wrong_answer_phrases = [
                f"answer is 'to {answer_l}'",
                f"answer is \"to {answer_l}\"",
                f"correct answer is 'to {answer_l}'",
                f"correct answer is \"to {answer_l}\"",
            ]

            if any(phrase in explanation_l for phrase in wrong_answer_phrases):
                return True

        if "past perfect" in explanation_l:
            past_perfect_markers = [
                "had ",
                "had been",
                "would have",
            ]

            if not any(marker in answer_l for marker in past_perfect_markers):
                if answer_l.startswith("was ") or answer_l.startswith("were "):
                    return True

        if "third conditional" in explanation_l:
            has_had_inversion = question_l.strip().startswith("had ")
            has_were_to_structure = (
                question_l.strip().startswith("were ")
                and " to " in question_l
            )
            has_would_have_answer = (
                "would have" in answer_l
                or "could have" in answer_l
                or "might have" in answer_l
            )

            if has_were_to_structure and not has_would_have_answer:
                return True

            if not has_had_inversion and not has_would_have_answer:
                return True

        if "present perfect" in explanation_l:
            present_perfect_markers_in_answer = [
                "has ",
                "have ",
                "has been",
                "have been",
            ]

            present_perfect_markers_in_question = [
                "has ",
                "have ",
                "has never",
                "have never",
                "has already",
                "have already",
            ]

            answer_has_marker = any(
                marker in answer_l
                for marker in present_perfect_markers_in_answer
            )

            question_has_marker = any(
                marker in question_l
                for marker in present_perfect_markers_in_question
            )

            if not answer_has_marker and not question_has_marker:
                return True

        return False

    def _complete_with_fallback_questions(
        self,
        questions: list[dict],
        session: Session,
        previous_questions: list[str] | None = None,
    ) -> list[dict]:
        previous_questions = previous_questions or []
        needed_count = self.MIN_VALID_QUESTIONS - len(questions)

        if needed_count <= 0:
            return questions

        Metrics.inc("quiz_validation_failures")

        fallback_questions = self._fallback_questions(session.level)
        existing_question_texts = [
            q.get("question", "")
            for q in questions
            if isinstance(q, dict)
        ]

        combined_previous = previous_questions + existing_question_texts

        fallback_validated = self._basic_validate_questions(
            questions=fallback_questions,
            previous_questions=combined_previous,
            level=session.level,
        )

        random.shuffle(fallback_validated)

        completed = questions[:]
        used_target_types = {
            q.get("target_type")
            for q in completed
            if isinstance(q, dict)
        }

        for fallback_question in fallback_validated:
            if len(completed) >= self.MIN_VALID_QUESTIONS:
                break

            target_type = fallback_question.get("target_type")
            if target_type in used_target_types:
                continue

            completed.append(fallback_question)
            used_target_types.add(target_type)

        if len(completed) < self.MIN_VALID_QUESTIONS:
            for fallback_question in fallback_validated:
                if len(completed) >= self.MIN_VALID_QUESTIONS:
                    break

                question_text = fallback_question.get("question")
                if not question_text:
                    continue

                if any(q.get("question") == question_text for q in completed):
                    continue

                completed.append(fallback_question)

        return completed

    def _start_fallback_quiz(self, session: Session):
        Metrics.inc("quiz_fallback_used")
        _logger.warning(
            "QUIZ FALLBACK USED. level=%s metrics=%s",
            session.level,
            Metrics.snapshot(),
        )

        self._ensure_quiz_state(session)

        fallback_questions = self._fallback_questions(session.level)
        previous_questions = session.data.get("previous_quiz_questions", [])

        validated_questions = self._basic_validate_questions(
            questions=fallback_questions,
            previous_questions=previous_questions,
            level=session.level,
        )

        if len(validated_questions) < self.MIN_VALID_QUESTIONS:
            validated_questions = fallback_questions

        selected_questions = self._select_balanced_questions(
            questions=validated_questions,
            count=self.MIN_VALID_QUESTIONS,
            level=session.level,
        )

        session.data["quiz_questions"] = selected_questions
        session.data["current_index"] = 0
        session.step = "waiting_quiz_answer"

        self._store_previous_questions(session, selected_questions)

        return self._format_current_question(session)

    def _select_balanced_questions(
        self,
        questions: list[dict],
        count: int = 5,
        level: str = "intermediate",
    ) -> list[dict]:
        if not questions:
            return []

        if level != "advanced" and len(questions) <= count:
            selected = questions[:]
            random.shuffle(selected)
            return selected

        shuffled = questions[:]
        random.shuffle(shuffled)

        selected = []
        used_target_types = set()
        pattern_counts = {}

        for question in shuffled:
            if len(selected) == count:
                return selected

            target_type = question.get("target_type")
            pattern_key = self._advanced_pattern_key(question) if level == "advanced" else None

            if target_type in used_target_types:
                continue

            if pattern_key and pattern_counts.get(pattern_key, 0) >= 2:
                continue

            selected.append(question)
            used_target_types.add(target_type)

            if pattern_key:
                pattern_counts[pattern_key] = pattern_counts.get(pattern_key, 0) + 1

        for question in shuffled:
            if len(selected) == count:
                return selected

            if question in selected:
                continue

            pattern_key = self._advanced_pattern_key(question) if level == "advanced" else None

            if pattern_key and pattern_counts.get(pattern_key, 0) >= 2:
                continue

            selected.append(question)

            if pattern_key:
                pattern_counts[pattern_key] = pattern_counts.get(pattern_key, 0) + 1

        if len(selected) < count:
            for question in shuffled:
                if len(selected) == count:
                    break

                if question in selected:
                    continue

                selected.append(question)

        return selected

    def _advanced_pattern_key(self, question: dict) -> str | None:
        question_text = question.get("question", "")
        explanation = question.get("explanation", "")
        target_type = question.get("target_type", "")

        if not isinstance(question_text, str):
            return None

        combined = f"{question_text} {explanation} {target_type}".lower()
        stripped = question_text.strip().lower()

        reduced_clause_markers = [
            "reduced relative clause",
            "reduced passive relative clause",
            "past participle",
            "participle",
        ]

        if any(marker in combined for marker in reduced_clause_markers):
            return "reduced_relative_clause"

        if stripped.startswith("were ") or "were the " in stripped:
            return "were_inverted_conditional"

        if stripped.startswith("had ") or "had the " in stripped:
            return "had_inverted_conditional"

        return None

    def _fallback_questions(self, level: str):
        fallback = {
            "beginner": [
                {
                    "question": "She ___ to school every day.",
                    "options": ["go", "goes", "going"],
                    "answer": "goes",
                    "explanation": "Use 'goes' for third person singular in the present simple.",
                    "target_type": "present simple",
                },
                {
                    "question": "They ___ football now.",
                    "options": ["play", "are playing", "played"],
                    "answer": "are playing",
                    "explanation": "Use the present continuous for an action happening now.",
                    "target_type": "present continuous",
                },
                {
                    "question": "I have ___ apple in my bag.",
                    "options": ["a", "an", "the"],
                    "answer": "an",
                    "explanation": "Use 'an' before a vowel sound.",
                    "target_type": "articles",
                },
                {
                    "question": "We went ___ bus.",
                    "options": ["by", "with", "at"],
                    "answer": "by",
                    "explanation": "Use 'by bus' for transport.",
                    "target_type": "basic prepositions",
                },
                {
                    "question": "My brother is very ___. He always helps people.",
                    "options": ["kind", "kinds", "kindly"],
                    "answer": "kind",
                    "explanation": "Use the adjective 'kind' after 'is'.",
                    "target_type": "basic vocabulary",
                },
                {
                    "question": "Tom and Anna ___ in the same class.",
                    "options": ["is", "are", "am"],
                    "answer": "are",
                    "explanation": "Use 'are' with plural subjects.",
                    "target_type": "subject verb agreement",
                },
                {
                    "question": "She usually ___ coffee in the morning.",
                    "options": ["drinks", "drink", "drinking"],
                    "answer": "drinks",
                    "explanation": "Use the present simple with 'usually' for habits.",
                    "target_type": "present simple",
                },
                {
                    "question": "Look! The children ___ in the garden.",
                    "options": ["are playing", "play", "played"],
                    "answer": "are playing",
                    "explanation": "Use present continuous for something happening now.",
                    "target_type": "present continuous",
                },
                {
                    "question": "There is ___ book on the table.",
                    "options": ["a", "an", "some"],
                    "answer": "a",
                    "explanation": "Use 'a' before a singular countable noun starting with a consonant sound.",
                    "target_type": "articles",
                },
                {
                    "question": "The cat is ___ the chair.",
                    "options": ["under", "slow", "happy"],
                    "answer": "under",
                    "explanation": "'Under' is a preposition of place.",
                    "target_type": "basic prepositions",
                },
                {
                    "question": "The opposite of 'cold' is ___.",
                    "options": ["hot", "old", "small"],
                    "answer": "hot",
                    "explanation": "'Hot' is the opposite of 'cold'.",
                    "target_type": "basic vocabulary",
                },
                {
                    "question": "My parents ___ at home today.",
                    "options": ["is", "are", "am"],
                    "answer": "are",
                    "explanation": "Use 'are' with the plural subject 'my parents'.",
                    "target_type": "subject verb agreement",
                },
            ],
            "intermediate": [
                {
                    "question": "If I had more time, I ___ take an online course.",
                    "options": ["would", "will", "am going to"],
                    "answer": "would",
                    "explanation": "Use 'would' in the second conditional for an unreal present situation.",
                    "target_type": "conditionals",
                },
                {
                    "question": "She ___ at this company since 2021.",
                    "options": ["has worked", "worked", "is working"],
                    "answer": "has worked",
                    "explanation": "Use the present perfect with 'since' for an action that started in the past and continues now.",
                    "target_type": "present perfect",
                },
                {
                    "question": "The report ___ before the meeting started.",
                    "options": ["had been finished", "has finished", "was finishing"],
                    "answer": "had been finished",
                    "explanation": "Use the past perfect passive for an action completed before another past event.",
                    "target_type": "passive voice",
                },
                {
                    "question": "The new policy is intended to ___ customer satisfaction.",
                    "options": ["improve", "improving", "improved"],
                    "answer": "improve",
                    "explanation": "After 'intended to', use the base verb: 'intended to improve'.",
                    "target_type": "gerund infinitive",
                },
                {
                    "question": "I avoid ___ emails late at night.",
                    "options": ["checking", "to check", "check"],
                    "answer": "checking",
                    "explanation": "The verb 'avoid' is followed by a gerund, so 'checking' is correct.",
                    "target_type": "gerund infinitive",
                },
                {
                    "question": "The word 'rapid' is closest in meaning to:",
                    "options": ["swift", "gradual", "delayed"],
                    "answer": "swift",
                    "explanation": "'Rapid' means fast or swift; 'gradual' means slow and step-by-step.",
                    "target_type": "collocations",
                },
                {
                    "question": "The company decided to ___ a new security system.",
                    "options": ["implement", "increase", "achieve"],
                    "answer": "implement",
                    "explanation": "The collocation 'implement a system' means to put a system into use.",
                    "target_type": "collocations",
                },
                {
                    "question": "She apologized ___ being late to the meeting.",
                    "options": ["for", "about", "to"],
                    "answer": "for",
                    "explanation": "The correct pattern is 'apologize for' a reason or action.",
                    "target_type": "modals",
                },
                {
                    "question": "The product was removed from the website because it ___ incorrectly.",
                    "options": ["had been listed", "has listed", "was listing"],
                    "answer": "had been listed",
                    "explanation": "Use the past perfect passive because the incorrect listing happened before the removal.",
                    "target_type": "passive voice",
                },
                {
                    "question": "We need someone who is capable ___ managing multiple tasks.",
                    "options": ["of", "for", "to"],
                    "answer": "of",
                    "explanation": "The correct pattern is 'capable of' followed by a noun or gerund.",
                    "target_type": "collocations",
                },
                {
                    "question": "The presentation was clear, but it lacked ___.",
                    "options": ["detail", "detailed", "detailing"],
                    "answer": "detail",
                    "explanation": "After 'lacked', a noun is needed; 'detail' is the correct noun here.",
                    "target_type": "collocations",
                },
                {
                    "question": "By the time we arrived, the tickets ___ sold out.",
                    "options": ["had already", "have already", "are already"],
                    "answer": "had already",
                    "explanation": "Use 'had already' for an action completed before another past action.",
                    "target_type": "present perfect",
                },
                {
                    "question": "This issue needs to be dealt ___ before the launch.",
                    "options": ["with", "about", "on"],
                    "answer": "with",
                    "explanation": "The correct phrasal verb is 'deal with' an issue.",
                    "target_type": "collocations",
                },
                {
                    "question": "He is not used to ___ in a noisy office.",
                    "options": ["working", "work", "worked"],
                    "answer": "working",
                    "explanation": "After 'be used to', use a noun or gerund, so 'working' is correct.",
                    "target_type": "gerund infinitive",
                },
                {
                    "question": "The instructions were so unclear that several users ___ mistakes.",
                    "options": ["made", "did", "created"],
                    "answer": "made",
                    "explanation": "The natural collocation is 'make mistakes'.",
                    "target_type": "collocations",
                },
                {
                    "question": "The meeting was postponed ___ the manager was unavailable.",
                    "options": ["because", "although", "unless"],
                    "answer": "because",
                    "explanation": "'Because' introduces the reason for the postponement.",
                    "target_type": "modals",
                },
                {
                    "question": "She has improved a lot since she ___ practicing every day.",
                    "options": ["started", "has started", "starts"],
                    "answer": "started",
                    "explanation": "Use past simple after 'since' when referring to the starting point of an action.",
                    "target_type": "present perfect",
                },
                {
                    "question": "The job requires someone who can work well ___ pressure.",
                    "options": ["under", "below", "in"],
                    "answer": "under",
                    "explanation": "The correct expression is 'work under pressure'.",
                    "target_type": "collocations",
                },
                {
                    "question": "The word 'reliable' is closest in meaning to:",
                    "options": ["dependable", "temporary", "ordinary"],
                    "answer": "dependable",
                    "explanation": "'Reliable' means dependable or trustworthy.",
                    "target_type": "collocations",
                },
                {
                    "question": "I look forward to ___ from you soon.",
                    "options": ["hearing", "hear", "heard"],
                    "answer": "hearing",
                    "explanation": "After 'look forward to', use a noun or gerund, so 'hearing' is correct.",
                    "target_type": "gerund infinitive",
                },
                {
                    "question": "Applicants ___ submit their documents before Friday.",
                    "options": ["must", "might", "could"],
                    "answer": "must",
                    "explanation": "Use 'must' to express a strong requirement.",
                    "target_type": "modals",
                },
                {
                    "question": "If she knew the answer, she ___ tell us.",
                    "options": ["would", "will", "is"],
                    "answer": "would",
                    "explanation": "Use 'would' in the second conditional for an unreal present situation.",
                    "target_type": "conditionals",
                },
                {
                    "question": "The documents ___ by the legal team yesterday.",
                    "options": ["were reviewed", "have reviewed", "are reviewing"],
                    "answer": "were reviewed",
                    "explanation": "Use the past simple passive when the focus is on the action and the time is finished.",
                    "target_type": "passive voice",
                },
                {
                    "question": "I have never ___ such a detailed report before.",
                    "options": ["seen", "saw", "see"],
                    "answer": "seen",
                    "explanation": "Use the past participle after 'have never' in the present perfect.",
                    "target_type": "present perfect",
                },
            ],
            "advanced": [
                {
                    "question": "Rarely ___ such a well-structured argument in a student essay.",
                    "options": ["I have seen", "have I seen", "I saw"],
                    "answer": "have I seen",
                    "explanation": "After negative adverbials like 'rarely', inversion is used.",
                    "target_type": "inversion",
                },
                {
                    "question": "Had they informed us earlier, we ___ the schedule.",
                    "options": ["would have changed", "would change", "changed"],
                    "answer": "would have changed",
                    "explanation": "This is an inverted third conditional.",
                    "target_type": "advanced conditionals",
                },
                {
                    "question": "Her proposal was rejected, not because it was impractical, but because it lacked ___.",
                    "options": ["coherence", "coherent", "coherently"],
                    "answer": "coherence",
                    "explanation": "A noun is needed after 'lacked'.",
                    "target_type": "advanced collocations",
                },
                {
                    "question": "The phrase closest in meaning to 'to undermine confidence' is:",
                    "options": ["to strengthen trust", "to weaken trust", "to ignore trust"],
                    "answer": "to weaken trust",
                    "explanation": "'Undermine confidence' means to weaken trust or belief.",
                    "target_type": "nuanced meaning",
                },
                {
                    "question": "No sooner ___ the announcement than the audience started asking questions.",
                    "options": ["had he finished", "he had finished", "did he finish"],
                    "answer": "had he finished",
                    "explanation": "Use inversion after 'no sooner'.",
                    "target_type": "inversion",
                },
                {
                    "question": "The report, ___ by an external consultant, raised several concerns.",
                    "options": ["written", "was written", "writing"],
                    "answer": "written",
                    "explanation": "A reduced passive relative clause can use the past participle 'written'.",
                    "target_type": "relative clauses",
                },
                {
                    "question": "The CEO gave a ___ response to the criticism.",
                    "options": ["measured", "measuring", "measure"],
                    "answer": "measured",
                    "explanation": "'A measured response' is a collocation meaning careful and controlled.",
                    "target_type": "formal register",
                },
                {
                    "question": "Were the policy to be implemented, it ___ significant resistance.",
                    "options": ["would face", "will face", "faces"],
                    "answer": "would face",
                    "explanation": "This is a formal inverted conditional with 'were'.",
                    "target_type": "advanced conditionals",
                },
                {
                    "question": "The candidate's argument was persuasive, albeit somewhat ___.",
                    "options": ["overstated", "overstate", "overstating"],
                    "answer": "overstated",
                    "explanation": "'Overstated' is the adjective needed after 'somewhat'.",
                    "target_type": "formal register",
                },
                {
                    "question": "The phrase closest in meaning to 'a marginal improvement' is:",
                    "options": ["a slight improvement", "a complete improvement", "an impossible improvement"],
                    "answer": "a slight improvement",
                    "explanation": "'Marginal' means small or slight in this context.",
                    "target_type": "nuanced meaning",
                },
                {
                    "question": "Only after reviewing the evidence ___ his position.",
                    "options": ["did he change", "he changed", "he did change"],
                    "answer": "did he change",
                    "explanation": "Use inversion after fronted restrictive phrases like 'only after'.",
                    "target_type": "inversion",
                },
                {
                    "question": "The strategy is unlikely to produce the desired outcome unless carefully ___.",
                    "options": ["implemented", "implementing", "implementation"],
                    "answer": "implemented",
                    "explanation": "A reduced passive structure requires the past participle 'implemented'.",
                    "target_type": "relative clauses",
                },
            ],
        }

        return fallback.get(level, fallback["beginner"])

    def _ensure_quiz_state(self, session: Session):
        if not hasattr(session, "data") or session.data is None:
            session.data = {}

        session.data.setdefault("previous_quiz_questions", [])
        session.data.setdefault("used_quiz_question_types", [])

    def _store_previous_questions(self, session: Session, questions: list[dict]):
        old_questions = session.data.get("previous_quiz_questions", [])
        if not isinstance(old_questions, list):
            old_questions = []

        new_question_texts = [
            question["question"]
            for question in questions
            if isinstance(question, dict) and isinstance(question.get("question"), str)
        ]

        combined_questions = old_questions + new_question_texts
        unique_questions = []
        seen = set()

        for question in combined_questions:
            if not isinstance(question, str) or not question.strip():
                continue

            normalized_question = question.strip().lower()
            if normalized_question in seen:
                continue

            seen.add(normalized_question)
            unique_questions.append(question.strip())

        session.data["previous_quiz_questions"] = unique_questions[-PREVIOUS_QUIZ_LIMIT:]