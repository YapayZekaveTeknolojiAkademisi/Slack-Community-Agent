import random

RECENT_TOPIC_LIMIT = 8
RECENT_TRANSLATION_LIMIT = 8
PREVIOUS_QUIZ_LIMIT = 30

SIMILARITY_THRESHOLD = 0.85
QUIZ_SIMILARITY_THRESHOLD = 0.82

MAX_REGENERATION_ATTEMPTS = 2


LEVEL_CONFIG = {
    "beginner": {
        "description": "Simple sentences, basic vocabulary",
        "max_words": 100,
        "topic_min_words": 30,
        "translation_min_words": 20,
    },
    "intermediate": {
        "description": "More complex sentences",
        "max_words": 200,
        "topic_min_words": 60,
        "translation_min_words": 40,
    },
    "advanced": {
        "description": "Fluent and detailed responses",
        "max_words": 300,
        "topic_min_words": 100,
        "translation_min_words": 70,
    }
}


WRITING_TOPIC_TASKS = {
    "beginner": [
        {"topic": "Describe your daily routine", "min_words": 30},
        {"topic": "Describe your favorite meal", "min_words": 30},
        {"topic": "Write about your favorite season", "min_words": 30},
        {"topic": "Describe a person you like", "min_words": 30},
        {"topic": "Write about your room", "min_words": 30},
        {"topic": "Describe your weekend plans", "min_words": 30},
        {"topic": "Write about your favorite animal", "min_words": 30},
        {"topic": "Describe your best friend", "min_words": 30},
    ],

    "intermediate": [
        {"topic": "Describe a memorable trip", "min_words": 60},
        {"topic": "Write about a challenge you overcame", "min_words": 60},
        {"topic": "Describe a useful mobile app", "min_words": 60},
        {"topic": "Explain why hobbies are important", "min_words": 60},
        {"topic": "Write about working from home", "min_words": 60},
        {"topic": "Describe a person who inspires you", "min_words": 60},
    ],

    "advanced": [
        {"topic": "Discuss the impact of technology on society", "min_words": 100},
        {"topic": "Discuss advantages of remote work", "min_words": 100},
        {"topic": "Explain importance of digital privacy", "min_words": 100},
        {"topic": "Discuss how automation may change careers", "min_words": 100},
        {"topic": "Explain why critical thinking matters", "min_words": 100},
    ],
}


TRANSLATION_TASKS = {
    "beginner": [
        {
            "source_text": "Ben her sabah erken kalkarım ve işe giderim.",
            "min_words":20
        },
        {
            "source_text":"Bugün hava çok güzel, parkta yürümek istiyorum.",
            "min_words":20
        },
        {
            "source_text":"Hafta sonları ailemle vakit geçirmeyi severim.",
            "min_words":20
        },
    ],

    "intermediate":[
        {
            "source_text":"Düzenli spor yapmak fiziksel ve zihinsel sağlık için önemlidir.",
            "min_words":40
        },
        {
            "source_text":"Yeni bir dil öğrenmek sabır ve düzenli pratik gerektirir.",
            "min_words":40
        },
    ],

    "advanced":[
        {
            "source_text":"Teknolojinin hızlı gelişimi hayatı kolaylaştırırken bazı sosyal etkiler de yaratıyor.",
            "min_words":70
        },
        {
            "source_text":"Yapay zekanın verimli kullanımı için etik sınırların korunması gerekir.",
            "min_words":70
        },
    ]
}


QUIZ_QUESTION_TYPES = {
    "beginner": [
        "present simple",
        "present continuous",
        "articles",
        "basic prepositions",
        "basic vocabulary",
        "subject verb agreement",
    ],

    "intermediate": [
        "present perfect",
        "conditionals",
        "modals",
        "passive voice",
        "collocations",
        "gerund infinitive",
    ],

    "advanced": [
        "inversion",
        "advanced conditionals",
        "formal register",
        "advanced collocations",
        "nuanced meaning",
        "relative clauses",
    ],
}


def _normalize(value):
    return value.strip().lower()


def _filter_recent(items,key,recent_values=None):
    recent_values = recent_values or []

    recent_set = {
        _normalize(v)
        for v in recent_values
        if isinstance(v,str)
    }

    filtered = [
        item for item in items
        if _normalize(item.get(key,"")) not in recent_set
    ]

    return filtered or items


def get_topic_tasks(level):
    return WRITING_TOPIC_TASKS.get(
        level,
        WRITING_TOPIC_TASKS["beginner"]
    )


def get_translation_tasks(level):
    return TRANSLATION_TASKS.get(
        level,
        TRANSLATION_TASKS["beginner"]
    )


def get_random_topic_task(level,recent_topics=None):
    tasks = get_topic_tasks(level)
    tasks = _filter_recent(
        tasks,
        "topic",
        recent_topics
    )
    return random.choice(tasks).copy()


def get_random_translation_task(level,recent_source_texts=None):
    tasks = get_translation_tasks(level)
    tasks = _filter_recent(
        tasks,
        "source_text",
        recent_source_texts
    )
    return random.choice(tasks).copy()


def get_random_quiz_question_types(level,count=5):
    qtypes = QUIZ_QUESTION_TYPES.get(
        level,
        QUIZ_QUESTION_TYPES["beginner"]
    )

    if count >= len(qtypes):
        temp = qtypes[:]
        random.shuffle(temp)
        return temp

    return random.sample(qtypes,count)