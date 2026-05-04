from services.english_service.core.quiz_mode import QuizMode
from services.english_service.llm.client import FakeLLMClient
from services.english_service.models import Session
from services.english_service.llm.client import FakeLLMClient


def make_session():
    s = Session("test")
    s.level="beginner"
    s.data={}
    return s


def test_quiz_starts():
    quiz = QuizMode(
        llm_client=FakeLLMClient(),
        validator_client=FakeLLMClient()
    )

    session = make_session()

    result = quiz.start_quiz(session)

    assert result["type"]=="quiz_question"


def test_no_duplicate_options():
    quiz = QuizMode(
   llm_client=FakeLLMClient(),
   validator_client=FakeLLMClient()
)

    sample=[
 {
   "question":"Choose the correct verb form.",
   "options":["go","goes","going"],
   "answer":"goes",
   "explanation":"Use third person singular in present simple."
 }
]

    validated=quiz._basic_validate_questions(sample)

    assert len(validated)==1


def test_duplicate_options_rejected():
    quiz = QuizMode(
    llm_client=FakeLLMClient(),
    validator_client=FakeLLMClient()
)
    bad=[
      {
       "question":"Bad",
       "options":["a","a","b"],
       "answer":"a",
       "explanation":"rule"
      }
    ]

    validated=quiz._basic_validate_questions(bad)

    assert validated==[]