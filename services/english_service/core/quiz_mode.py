import ast

from services.english_service.models import Session
from services.english_service.core.prompt_builder import (
    build_quiz_prompt,
    build_quiz_validation_prompt,
)
from services.english_service.llm.client import BaseLLMClient, GroqLLMClient


class QuizMode:
    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        validator_client: BaseLLMClient | None = None,
    ):
        self.llm = llm_client or GroqLLMClient(
            temperature=0.8,
            system_message="You generate varied and level-appropriate English quiz questions."
        )
        self.validator_llm = validator_client or GroqLLMClient(
            temperature=0.2,
            system_message="You carefully validate English quiz questions and remove wrong or ambiguous items."
        )

    def start_quiz(self, session: Session):
        previous_questions = session.data.get("previous_quiz_questions", [])

        prompt = build_quiz_prompt(
            level=session.level,
            question_count=8,
            previous_questions=previous_questions,
        )

        llm_response = self.llm.generate(prompt)
        print("QUIZ RAW RESPONSE:")
        print(llm_response)

        try:
            questions = ast.literal_eval(llm_response)
        except Exception:
            return self._start_fallback_quiz(session)

        validated_questions = self._basic_validate_questions(
            questions,
            previous_questions,
        )

        if not validated_questions:
            return self._start_fallback_quiz(session)

        llm_validated_questions = self._llm_validate_questions(
            validated_questions,
            session.level,
        )

        if llm_validated_questions:
            validated_questions = self._basic_validate_questions(
                llm_validated_questions,
                previous_questions,
            )

        if len(validated_questions) < 5:
            return self._start_fallback_quiz(session)

        session.data["quiz_questions"] = validated_questions[:5]
        session.data["current_index"] = 0
        session.step = "waiting_quiz_answer"

        old_questions = session.data.get("previous_quiz_questions", [])
        new_question_texts = [q["question"] for q in session.data["quiz_questions"]]
        session.data["previous_quiz_questions"] = (old_questions + new_question_texts)[-20:]

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
                "message": "This quiz question is invalid. Please start a new quiz."
            }

        try:
            selected_index = int(selected_value) - 1
            if selected_index < 0 or selected_index >= len(options):
                raise ValueError("Selected option index is out of range.")
            selected_option = options[selected_index]
        except Exception:
            return {
                "type": "quiz_feedback",
                "message": "Please choose a valid option number."
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
            "next": next_question
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
            )
        }

    def finish_quiz(self, session: Session):
        session.step = "quiz_finished"
        return {
            "type": "quiz_result",
            "message": "Quiz finished."
        }

    def _basic_validate_questions(
        self,
        questions,
        previous_questions: list[str] | None = None,
    ):
        if not isinstance(questions, list):
            return []

        previous_questions = previous_questions or []
        previous_lower = {q.strip().lower() for q in previous_questions}

        validated = []
        seen_current = set()

        banned_patterns = [
            "by the time i arrived",
            "by next year, i",
            "if i won the lottery",
            "she is not used to",
            "i wish i",
        ]

        for q in questions:
            if not isinstance(q, dict):
                continue

            question = q.get("question")
            options = q.get("options")
            answer = q.get("answer")
            explanation = q.get("explanation", "")

            if not isinstance(question, str) or not question.strip():
                continue

            cleaned_question = question.strip()
            lowered_question = cleaned_question.lower()

            if lowered_question in previous_lower:
                continue

            if lowered_question in seen_current:
                continue

            if any(pattern in lowered_question for pattern in banned_patterns):
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

            if len(cleaned_question) < 10:
                continue

            validated.append({
                "question": cleaned_question,
                "options": cleaned_options,
                "answer": canonical_answer,
                "explanation": explanation.strip(),
            })

            seen_current.add(lowered_question)

        return validated

    def _llm_validate_questions(self, questions: list[dict], level: str):
        prompt = build_quiz_validation_prompt(questions, level)
        response = self.validator_llm.generate(prompt)

        print("QUIZ VALIDATION RESPONSE:")
        print(response)

        try:
            validated_questions = ast.literal_eval(response)
        except Exception:
            return questions

        if not isinstance(validated_questions, list):
            return questions

        return validated_questions

    def _start_fallback_quiz(self, session: Session):
        fallback_questions = self._fallback_questions(session.level)
        previous_questions = session.data.get("previous_quiz_questions", [])

        validated_questions = self._basic_validate_questions(
            fallback_questions,
            previous_questions,
        )

        if len(validated_questions) < 5:
            validated_questions = fallback_questions

        session.data["quiz_questions"] = validated_questions[:5]
        session.data["current_index"] = 0
        session.step = "waiting_quiz_answer"

        old_questions = session.data.get("previous_quiz_questions", [])
        new_question_texts = [q["question"] for q in session.data["quiz_questions"]]
        session.data["previous_quiz_questions"] = (old_questions + new_question_texts)[-20:]

        return self._format_current_question(session)

    def _fallback_questions(self, level: str):
        fallback = {
            "beginner": [
                {
                    "question": "She ___ to school every day.",
                    "options": ["go", "goes", "going"],
                    "answer": "goes",
                    "explanation": "Use 'goes' for third person singular in the present simple."
                },
                {
                    "question": "They ___ football now.",
                    "options": ["play", "are playing", "played"],
                    "answer": "are playing",
                    "explanation": "Use present continuous for an action happening now."
                },
                {
                    "question": "I have ___ apple in my bag.",
                    "options": ["a", "an", "the"],
                    "answer": "an",
                    "explanation": "Use 'an' before a vowel sound."
                },
                {
                    "question": "We went ___ bus.",
                    "options": ["by", "with", "at"],
                    "answer": "by",
                    "explanation": "Use 'by bus' for transport."
                },
                {
                    "question": "My brother is very ___. He always helps people.",
                    "options": ["kind", "kinds", "kindly"],
                    "answer": "kind",
                    "explanation": "Use the adjective 'kind' after 'is'."
                },
            ],
            "intermediate": [
                {
                    "question": "If I had more time, I ___ learn Spanish.",
                    "options": ["would", "will", "am"],
                    "answer": "would",
                    "explanation": "Use 'would' in the second conditional."
                },
                {
                    "question": "She ___ in this company since 2021.",
                    "options": ["has worked", "worked", "works"],
                    "answer": "has worked",
                    "explanation": "Use present perfect with 'since' for an action continuing to the present."
                },
                {
                    "question": "You ___ wear a seatbelt while driving.",
                    "options": ["must", "might", "could"],
                    "answer": "must",
                    "explanation": "Use 'must' for strong obligation."
                },
                {
                    "question": "This word is closest in meaning to 'rapid':",
                    "options": ["slow", "quick", "late"],
                    "answer": "quick",
                    "explanation": "'Rapid' means 'quick'."
                },
                {
                    "question": "The report ___ before the meeting started.",
                    "options": ["had been finished", "has finished", "was finishing"],
                    "answer": "had been finished",
                    "explanation": "Use past perfect passive for an action completed before another past event."
                },
            ],
            "advanced": [
                {
                    "question": "Rarely ___ such a well-structured argument in a student essay.",
                    "options": ["I have seen", "have I seen", "I saw"],
                    "answer": "have I seen",
                    "explanation": "After negative adverbials like 'rarely', inversion is used."
                },
                {
                    "question": "Had they informed us earlier, we ___ the schedule.",
                    "options": ["would have changed", "would change", "changed"],
                    "answer": "would have changed",
                    "explanation": "This is an inverted third conditional."
                },
                {
                    "question": "Her proposal was rejected, not because it was impractical, but because it lacked ___.",
                    "options": ["coherence", "coherent", "coherently"],
                    "answer": "coherence",
                    "explanation": "A noun is needed after 'lacked'."
                },
                {
                    "question": "The phrase closest in meaning to 'to undermine confidence' is:",
                    "options": ["to strengthen trust", "to weaken trust", "to ignore trust"],
                    "answer": "to weaken trust",
                    "explanation": "'Undermine confidence' means to weaken trust or belief."
                },
                {
                    "question": "No sooner ___ the announcement than the audience started asking questions.",
                    "options": ["had he finished", "he had finished", "did he finish"],
                    "answer": "had he finished",
                    "explanation": "Use inversion after 'no sooner'."
                },
            ],
        }

        return fallback.get(level, fallback["beginner"])