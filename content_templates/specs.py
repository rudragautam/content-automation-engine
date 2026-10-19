"""What each niche's content spreadsheet contains.

One spec per niche drives three things so they never disagree: the
downloadable Excel template, the AI prompt inside it, and validation of
the filled sheet when it is uploaded back.

A sheet has one row per video. Columns are, in order: YouTube details,
the intro slide, then numbered groups for each content slide
(habit1_title, habit1_text, habit2_title, ...).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

POSITIONS = ("left", "right", "center")
ANSWERS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class Field:
    key: str  # key in the template's data, e.g. "title"
    description: str
    max_len: Optional[int] = None
    required: bool = True
    choices: Tuple[str, ...] = ()
    kind: str = "text"  # text | url | bars | answer


@dataclass(frozen=True)
class ItemGroup:
    prefix: str  # column prefix, e.g. "habit" -> habit1_title
    label: str  # what one item is called, e.g. "habit"
    min_count: int
    max_count: int
    fields: Tuple[Field, ...]


@dataclass(frozen=True)
class NicheSpec:
    niche: str
    name: str
    template_id: str
    aspect_ratio: str
    language: str
    audience_and_tone: str
    intro_fields: Tuple[Field, ...]
    items: ItemGroup
    example: Dict[str, str] = field(default_factory=dict)

    def columns(self) -> List[Tuple[str, str, Field]]:
        """(column name, group label, field) for every column, in sheet order."""
        cols = [(f"{f.key}", "YouTube", f) for f in VIDEO_FIELDS]
        cols += [(f"intro_{f.key}", "Intro slide", f) for f in self.intro_fields]
        for n in range(1, self.items.max_count + 1):
            label = f"{self.items.label.title()} {n}"
            cols += [(f"{self.items.prefix}{n}_{f.key}", label, f) for f in self.items.fields]
        return cols


VIDEO_FIELDS = (
    Field("video_id", "Your own unique ID for this video, e.g. FH-001. Left blank, one is generated.", 40, required=False),
    Field("publish_at", "When the video goes public, in the channel's timezone: YYYY-MM-DD HH:MM. Left blank, the channel's next free slot is used.", 16, required=False),
    Field("youtube_title", "Title shown on YouTube. Clear and curiosity-driven, no clickbait.", 100),
    Field("youtube_description", "Description shown under the video. 2-4 short lines, may end with 3-5 hashtags.", 5000),
    Field("youtube_tags", "Comma-separated search tags, 500 characters in total at most.", 500, required=False),
)

IMAGE = Field("image", "Background image URL. Leave blank if you don't have one.", 500, required=False, kind="url")
POSITION = Field("text_position", "Where the text box sits: left, right or center. Blank alternates left and right.", required=False, choices=POSITIONS)

FOCUS_HABITS = NicheSpec(
    niche="focus_habits",
    name="Focus & Habits",
    template_id="01_Focus_Habits_Shorts_9x16",
    aspect_ratio="9:16",
    language="English",
    audience_and_tone="Students and young professionals. Direct, practical, motivating; one clear idea per slide.",
    intro_fields=(
        Field("kicker", "Small label above the title, in capitals, e.g. DAILY MINDSET.", 24),
        Field("title", "The hook: the video's promise, e.g. 5 Daily Habits That Ruin Your Focus.", 60),
        Field("text", "One sentence that sets up the list.", 110),
        Field("micro", "Optional tiny call to action, e.g. WATCH TILL THE END.", 28, required=False),
    ),
    items=ItemGroup("habit", "habit", 3, 8, (
        Field("title", "Habit name in capitals, may start with one emoji, e.g. 📱 PHONE CHECKING.", 32),
        Field("text", "One sentence: why it hurts focus. It is typed out on screen.", 120),
    )),
    example={
        "video_id": "FH-001", "publish_at": "",
        "youtube_title": "5 Daily Habits That Quietly Ruin Your Focus",
        "youtube_description": "Small habits, big impact on your concentration.\nWhich one do you do every day?\n#focus #productivity #habits",
        "youtube_tags": "focus, productivity, study tips, habits, concentration",
        "intro_kicker": "DAILY MINDSET", "intro_title": "5 Daily Habits That Ruin Your Focus",
        "intro_text": "Some habits quietly destroy your concentration without you noticing.", "intro_micro": "WATCH TILL THE END",
        "habit1_title": "📱 PHONE CHECKING", "habit1_text": "Checking your phone every few minutes destroys deep focus before it even begins.",
        "habit2_title": "🔔 CONSTANT NOTIFICATIONS", "habit2_text": "Every ping forces your brain to switch context, making simple work take much longer.",
        "habit3_title": "🌙 POOR SLEEP", "habit3_text": "When sleep is consistently low, attention, memory and decision-making all suffer.",
        "habit4_title": "🧠 MULTITASKING", "habit4_text": "Doing several things at once feels productive, but your brain keeps paying a switching cost.",
        "habit5_title": "🍩 SUGAR CRASHES", "habit5_text": "Quick sugar gives a short spike of energy, then leaves you foggy and distracted.",
    },
)

GEETA_GYAAN = NicheSpec(
    niche="geeta_gyaan",
    name="Geeta Gyaan",
    template_id="02_Geeta_Gyaan_9x16",
    aspect_ratio="9:16",
    language="Hindi (Devanagari script) for all on-screen text; YouTube title and description may be Hindi or Hinglish",
    audience_and_tone="Hindi-speaking viewers seeking calm, practical life lessons from the Bhagavad Gita. Respectful, warm, simple words; faithful to the Gita's teaching, no invented verses.",
    intro_fields=(
        Field("title", "The video's theme in Hindi, e.g. श्रीमद्भगवद्गीता से जीवन के सूत्र.", 50),
        Field("text", "One short Hindi line that sets up the lessons.", 80),
    ),
    items=ItemGroup("lesson", "lesson", 3, 6, (
        Field("chapter", "One-word theme in Hindi, e.g. कर्म, धैर्य, सत्य.", 16),
        Field("title", "The lesson in a few Hindi words.", 40),
        Field("text", "One or two Hindi sentences explaining the lesson in daily life.", 140),
        IMAGE,
    )),
    example={
        "video_id": "GG-001", "publish_at": "",
        "youtube_title": "गीता के 4 सूत्र जो जीवन बदल दें | Geeta Gyaan",
        "youtube_description": "श्रीमद्भगवद्गीता से चार सरल सीख।\nकौन सा सूत्र आपको सबसे अच्छा लगा?\n#GeetaGyaan #Krishna #Motivation",
        "youtube_tags": "geeta gyaan, bhagavad gita, krishna, गीता, motivation hindi",
        "intro_title": "श्रीमद्भगवद्गीता से जीवन के सूत्र", "intro_text": "एक विचार। एक सीख। एक नया दृष्टिकोण।",
        "lesson1_chapter": "कर्म", "lesson1_title": "कर्म करते जाओ", "lesson1_text": "अपने कर्म पर अधिकार रखो, परिणाम की चिंता में अपने वर्तमान को मत खोओ।", "lesson1_image": "",
        "lesson2_chapter": "धैर्य", "lesson2_title": "मन को स्थिर रखो", "lesson2_text": "जब मन स्थिर होता है, तब कठिन परिस्थितियों में भी सही निर्णय दिखाई देने लगता है।", "lesson2_image": "",
        "lesson3_chapter": "सत्य", "lesson3_title": "सत्य का मार्ग", "lesson3_text": "सही मार्ग हमेशा आसान नहीं होता, लेकिन वही भीतर की शांति की ओर ले जाता है।", "lesson3_image": "",
        "lesson4_chapter": "ज्ञान", "lesson4_title": "ज्ञान भीतर से जागता है", "lesson4_text": "प्रश्न करना शुरुआत है; अनुभव, चिंतन और सत्य की खोज ज्ञान को गहरा बनाते हैं।", "lesson4_image": "",
    },
)


def _quiz_fields():
    return (
        Field("category", "Subject in capitals, e.g. SCIENCE, HISTORY, SPACE.", 16),
        Field("question", "The question, one sentence.", 90),
        Field("option_a", "Answer option A.", 32),
        Field("option_b", "Answer option B.", 32),
        Field("option_c", "Answer option C.", 32),
        Field("option_d", "Answer option D.", 32),
        Field("correct", "Letter of the correct option: A, B, C or D.", choices=ANSWERS, kind="answer"),
        Field("explanation", "One sentence explaining why the answer is correct. Must be factually accurate.", 110),
    )


GENERAL_QUIZ = NicheSpec(
    niche="general_quiz",
    name="General Knowledge Quiz",
    template_id="03_General_Quiz_9x16",
    aspect_ratio="9:16",
    language="English",
    audience_and_tone="General audience, school level and up. Fun and challenging; exactly one correct answer, plausible wrong options, verified facts.",
    intro_fields=(
        Field("title", "The challenge, e.g. Can You Score 4/4?", 40),
        Field("text", "One short line, e.g. Swipe up and test yourself.", 60),
    ),
    items=ItemGroup("q", "question", 3, 6, _quiz_fields()),
    example={
        "video_id": "GQ-001", "publish_at": "",
        "youtube_title": "Only 1 in 10 Score 4/4 on This Quiz",
        "youtube_description": "Four quick questions. How many did you get right?\nComment your score!\n#quiz #generalknowledge #trivia",
        "youtube_tags": "quiz, general knowledge, trivia, gk quiz",
        "intro_title": "Can You Score 4/4?", "intro_text": "Swipe up and test yourself.",
        "q1_category": "SCIENCE", "q1_question": "Which planet is known as the Red Planet?", "q1_option_a": "Earth", "q1_option_b": "Mars", "q1_option_c": "Jupiter", "q1_option_d": "Venus", "q1_correct": "B", "q1_explanation": "Mars appears reddish because iron minerals in its surface have oxidized.",
        "q2_category": "HISTORY", "q2_question": "Who wrote the Arthashastra?", "q2_option_a": "Kalidasa", "q2_option_b": "Chanakya", "q2_option_c": "Aryabhata", "q2_option_d": "Panini", "q2_correct": "B", "q2_explanation": "The Arthashastra is traditionally attributed to Chanakya, also known as Kautilya.",
        "q3_category": "SPACE", "q3_question": "What is the largest planet in our Solar System?", "q3_option_a": "Saturn", "q3_option_b": "Earth", "q3_option_c": "Jupiter", "q3_option_d": "Neptune", "q3_correct": "C", "q3_explanation": "Jupiter is the largest planet by diameter and mass.",
        "q4_category": "BIOLOGY", "q4_question": "Which organ pumps blood through the human body?", "q4_option_a": "Liver", "q4_option_b": "Brain", "q4_option_c": "Heart", "q4_option_d": "Lung", "q4_correct": "C", "q4_explanation": "The heart contracts rhythmically to circulate blood.",
    },
)

SCIENCE_QUIZ = NicheSpec(
    niche="science_quiz",
    name="Science Quiz",
    template_id="04_Science_Quiz_9x16",
    aspect_ratio="9:16",
    language="English",
    audience_and_tone="Curious students and science fans. Physics, chemistry, biology and astronomy; exactly one correct answer, verified facts.",
    intro_fields=(
        Field("title", "The challenge, e.g. Think You Know Science?", 40),
        Field("text", "One short line, e.g. Four questions. One score.", 60),
    ),
    # The template shows "n/4" and a "0 / 4" result, so it needs exactly four questions.
    items=ItemGroup("q", "question", 4, 4, _quiz_fields()),
    example={
        "video_id": "SQ-001", "publish_at": "",
        "youtube_title": "Think You Know Science? 4 Quick Questions",
        "youtube_description": "Physics, biology, chemistry and space in one quiz.\nComment your score!\n#science #quiz #stem",
        "youtube_tags": "science quiz, physics, biology, chemistry, astronomy",
        "intro_title": "Think You Know Science?", "intro_text": "Four questions. One score.",
        "q1_category": "PHYSICS", "q1_question": "What force keeps planets in orbit around the Sun?", "q1_option_a": "Magnetism", "q1_option_b": "Gravity", "q1_option_c": "Friction", "q1_option_d": "Electricity", "q1_correct": "B", "q1_explanation": "Gravity provides the inward force that keeps planets in orbital motion.",
        "q2_category": "BIOLOGY", "q2_question": "Which part of a cell contains most of its genetic material?", "q2_option_a": "Cell wall", "q2_option_b": "Nucleus", "q2_option_c": "Ribosome", "q2_option_d": "Cytoplasm", "q2_correct": "B", "q2_explanation": "In eukaryotic cells, most DNA is stored inside the nucleus.",
        "q3_category": "CHEMISTRY", "q3_question": "What is the chemical symbol for oxygen?", "q3_option_a": "Ox", "q3_option_b": "O", "q3_option_c": "Og", "q3_option_d": "C", "q3_correct": "B", "q3_explanation": "O is the standard chemical symbol for oxygen.",
        "q4_category": "ASTRONOMY", "q4_question": "What galaxy contains our Solar System?", "q4_option_a": "Andromeda", "q4_option_b": "Triangulum", "q4_option_c": "Milky Way", "q4_option_d": "Whirlpool", "q4_correct": "C", "q4_explanation": "Our Solar System is located in the Milky Way galaxy.",
    },
)


def _story_niche(niche, name, template_id, aspect, language, tone, title_len, text_len, kicker_example, example):
    return NicheSpec(
        niche=niche, name=name, template_id=template_id, aspect_ratio=aspect, language=language,
        audience_and_tone=tone,
        intro_fields=(
            Field("kicker", f"Small label above the title, in capitals, e.g. {kicker_example}.", 30),
            Field("title", "The story's title, in capitals.", 40),
            Field("text", "One sentence that sets up the story.", 110),
        ),
        items=ItemGroup("scene", "scene", 3, 6, (
            Field("chapter", "Short scene label in capitals, e.g. THE BEGINNING.", 22),
            Field("title", "Scene headline in capitals.", title_len),
            Field("text", "Narration for this scene, 1-2 sentences.", text_len),
            IMAGE,
            POSITION,
        )),
        example=example,
    )


SCIENCE_STORY = _story_niche(
    "science_story", "Science Storytelling", "05_Science_Storytelling_9x16", "9:16", "English",
    "Curious general audience. A short narrative that builds from a hook to one big idea; accurate science, vivid but plain language.",
    48, 150, "KNOWLEDGE • STORY",
    {
        "video_id": "SS-001", "publish_at": "",
        "youtube_title": "How Watching the Sky Became Science",
        "youtube_description": "From star-watching to the scientific method in under a minute.\n#science #history #space",
        "youtube_tags": "science history, astronomy, scientific method",
        "intro_kicker": "KNOWLEDGE • STORY", "intro_title": "SCIENCE THROUGH TIME", "intro_text": "A journey from ancient observation to the questions that shaped science.",
        "scene1_chapter": "SCIENCE", "scene1_title": "WHEN THE SKY WAS OUR FIRST LABORATORY", "scene1_text": "Long before modern instruments existed, humans looked toward the sky to understand time, seasons and the world around them.", "scene1_image": "", "scene1_text_position": "left",
        "scene2_chapter": "ANCIENT KNOWLEDGE", "scene2_title": "WE LEARNED BY WATCHING THE STARS", "scene2_text": "The movement of the Sun, Moon and stars helped ancient civilizations build calendars and understand recurring patterns in nature.", "scene2_image": "", "scene2_text_position": "right",
        "scene3_chapter": "ASTRONOMY", "scene3_title": "THE UNIVERSE BECAME A QUESTION", "scene3_text": "Every observation created another question. Why do objects move? Why does light travel? What lies beyond what we can see?", "scene3_image": "", "scene3_text_position": "left",
        "scene4_chapter": "THE BIG IDEA", "scene4_title": "CURIOSITY BECAME SCIENCE", "scene4_text": "Science grows from a simple human habit: observe carefully, question honestly, and keep searching for a better explanation.", "scene4_image": "", "scene4_text_position": "center",
    },
)

INDIAN_TRADITIONAL_STORY = _story_niche(
    "indian_traditional_story", "Indian Traditional Stories", "06_Indian_Traditional_Story_9x16", "9:16",
    "English, or Hindi in Devanagari script; keep one language per video",
    "Families and young viewers who enjoy Indian traditions, festivals and legends. Warm storytelling; present legends as legends and history as history.",
    48, 150, "KNOWLEDGE • STORY",
    {
        "video_id": "IT-001", "publish_at": "",
        "youtube_title": "Why We Light Diyas on Diwali",
        "youtube_description": "The story behind the festival of lights.\n#Diwali #IndianFestivals #Ramayana",
        "youtube_tags": "diwali story, ramayana, indian festivals, diya",
        "intro_kicker": "KNOWLEDGE • STORY", "intro_title": "THE STORY OF DIWALI", "intro_text": "Why millions of lamps light up India every autumn.",
        "scene1_chapter": "THE EXILE", "scene1_title": "FOURTEEN YEARS AWAY FROM HOME", "scene1_text": "In the Ramayana, Prince Rama spends fourteen years in exile in the forest with Sita and Lakshmana.", "scene1_image": "", "scene1_text_position": "left",
        "scene2_chapter": "THE BATTLE", "scene2_title": "GOOD OVER EVIL", "scene2_text": "Rama defeats the demon king Ravana and rescues Sita, a victory of good over evil.", "scene2_image": "", "scene2_text_position": "right",
        "scene3_chapter": "THE RETURN", "scene3_title": "AYODHYA LIGHTS THE WAY", "scene3_text": "When Rama returns to Ayodhya, its people light rows of clay lamps to welcome him home.", "scene3_image": "", "scene3_text_position": "left",
        "scene4_chapter": "THE TRADITION", "scene4_title": "A FESTIVAL OF LIGHT", "scene4_text": "Lighting diyas on Diwali carries that welcome forward: light chasing away darkness, hope over despair.", "scene4_image": "", "scene4_text_position": "center",
    },
)

INDIAN_HERITAGE_STORY = _story_niche(
    "indian_heritage_story", "Indian Heritage (16:9)", "07_Indian_Heritage_Story_16x9", "16:9", "English",
    "Viewers interested in Indian history, monuments and science. Documentary tone; accurate dates and names.",
    60, 170, "INDIAN HERITAGE • STORY",
    {
        "video_id": "IH-001", "publish_at": "",
        "youtube_title": "Konark Sun Temple: A Chariot Made of Stone",
        "youtube_description": "How a 13th-century temple was built as a giant stone chariot for the Sun god.\n#Konark #IndianHeritage #History",
        "youtube_tags": "konark sun temple, odisha, indian history, unesco heritage",
        "intro_kicker": "INDIAN HERITAGE • STORY", "intro_title": "THE CHARIOT OF THE SUN", "intro_text": "A temple in Odisha designed as a giant chariot carved in stone.",
        "scene1_chapter": "THE KING", "scene1_title": "BUILT IN THE 13TH CENTURY", "scene1_text": "The Konark Sun Temple was built around 1250 CE by King Narasimhadeva I of the Eastern Ganga dynasty.", "scene1_image": "", "scene1_text_position": "left",
        "scene2_chapter": "THE DESIGN", "scene2_title": "A CHARIOT WITH TWENTY-FOUR WHEELS", "scene2_text": "The temple is shaped as the chariot of Surya, the Sun god, with twenty-four carved stone wheels pulled by seven horses.", "scene2_image": "", "scene2_text_position": "right",
        "scene3_chapter": "THE WHEELS", "scene3_title": "STONE WHEELS THAT TELL TIME", "scene3_text": "The shadows cast by the spokes of the wheels can be read like a sundial to tell the time of day.", "scene3_image": "", "scene3_text_position": "left",
        "scene4_chapter": "THE LEGACY", "scene4_title": "A WORLD HERITAGE SITE", "scene4_text": "UNESCO listed the Sun Temple as a World Heritage Site in 1984 for its architecture and sculpture.", "scene4_image": "", "scene4_text_position": "center",
    },
)

CRIME_FILES = NicheSpec(
    niche="crime_files",
    name="Crime Files (16:9)",
    template_id="08_Crime_Files_16x9",
    aspect_ratio="16:9",
    language="English",
    audience_and_tone="Adult true-crime and mystery fans. Suspenseful, restrained, never graphic or sensational; for real cases, only verified facts and no speculation about named people.",
    intro_fields=(
        Field("kicker", "Small label above the title, in capitals, e.g. A CINEMATIC CRIME SERIES.", 30),
        Field("title", "Series or case title, in capitals, e.g. CRIME FILES.", 24),
        Field("text", "One suspenseful line.", 90),
    ),
    items=ItemGroup("scene", "scene", 3, 6, (
        Field("chapter", "Scene label in capitals, e.g. CASE FILE 001, EVIDENCE, THE CLUE.", 22),
        Field("title", "Scene headline in capitals.", 48),
        Field("text", "Narration for this scene, 1-2 sentences.", 170),
        IMAGE,
        POSITION,
    )),
    example={
        "video_id": "CF-001", "publish_at": "",
        "youtube_title": "The Night the City Went Silent | Crime Files",
        "youtube_description": "A rainy night, an empty street and a clue that made no sense.\n#CrimeFiles #Mystery #Storytime",
        "youtube_tags": "crime story, mystery, case file, investigation",
        "intro_kicker": "A CINEMATIC CRIME SERIES", "intro_title": "CRIME FILES", "intro_text": "Every crime leaves a story. Every story leaves a clue.",
        "scene1_chapter": "CASE FILE 001", "scene1_title": "THE NIGHT THE CITY WENT SILENT", "scene1_text": "It was raining heavily that night. The streets were almost empty. Then, somewhere in the darkness, a crime changed everything.", "scene1_image": "", "scene1_text_position": "left",
        "scene2_chapter": "EVIDENCE", "scene2_title": "A SINGLE LINE OF TAPE", "scene2_text": "By morning, yellow crime scene tape had sealed the street. Investigators knew one thing: whoever did this had left something behind.", "scene2_image": "", "scene2_text_position": "right",
        "scene3_chapter": "THE CLUE", "scene3_title": "THE MARK ON THE WALL", "scene3_text": "Inside the abandoned room, investigators found a mark on the wall. Was it a warning, a signature, or an attempt to mislead them?", "scene3_image": "", "scene3_text_position": "left",
        "scene4_chapter": "THE QUESTION", "scene4_title": "BUT WHO WAS REALLY THERE?", "scene4_text": "Three clues. One location. And a timeline that did not make sense. The deeper investigators looked, the stranger the case became.", "scene4_image": "", "scene4_text_position": "center",
    },
)

AI_NEURAL = NicheSpec(
    niche="ai_neural_intelligence",
    name="AI — Neural Intelligence (16:9)",
    template_id="14_AI_Neural_Intelligence_16x9",
    aspect_ratio="16:9",
    language="English",
    audience_and_tone="Tech-curious viewers and professionals. Clear explainer tone; accurate, no hype, no claims about specific unreleased products.",
    intro_fields=(
        Field("kicker", "Small label above the title, in capitals, e.g. ARTIFICIAL INTELLIGENCE / SERIES 01.", 40),
        Field("title", "Big title in capitals, 2-4 words, e.g. THE AGE OF INTELLIGENCE.", 40),
        Field("text", "Keywords line in capitals separated by •, e.g. MODELS • DATA • MACHINES.", 60),
    ),
    # The template draws exactly four progress dots and "01 / 04".
    items=ItemGroup("scene", "scene", 4, 4, (
        Field("section", "Section label in capitals, e.g. GENERATIVE AI.", 20),
        Field("title", "Headline in capitals, one strong statement.", 80),
        Field("narration", "Narration typed out on screen, 2 sentences.", 200),
        IMAGE,
        POSITION,
        Field("signal", "Panel keyword in capitals, one word, e.g. PATTERN.", 10),
        Field("sub", "Panel subtitle in capitals, e.g. LEARNING.", 12),
        Field("m1", "Panel tag 1, one short word in capitals.", 8),
        Field("m2", "Panel tag 2, one short word in capitals.", 8),
        Field("m3", "Panel tag 3, one short word in capitals.", 8),
        Field("m4", "Panel tag 4, one short word in capitals.", 8),
    )),
    example={
        "video_id": "AN-001", "publish_at": "",
        "youtube_title": "How AI Actually Works (No Hype)",
        "youtube_description": "Patterns, generation, augmentation and the human choices behind AI.\n#AI #MachineLearning #Tech",
        "youtube_tags": "artificial intelligence, machine learning, generative ai, ai explained",
        "intro_kicker": "ARTIFICIAL INTELLIGENCE / SERIES 01", "intro_title": "THE AGE OF INTELLIGENCE.", "intro_text": "MODELS • DATA • MACHINES • HUMAN CURIOSITY",
        "scene1_section": "AI SYSTEMS", "scene1_title": "AI DOES NOT THINK LIKE A HUMAN — IT FINDS PATTERNS AT SCALE", "scene1_narration": "Modern AI systems learn statistical patterns from enormous amounts of data. That lets them generate predictions, language and images at remarkable speed.", "scene1_image": "", "scene1_text_position": "left", "scene1_signal": "PATTERN", "scene1_sub": "LEARNING", "scene1_m1": "DATA", "scene1_m2": "MODEL", "scene1_m3": "SCALE", "scene1_m4": "PREDICT",
        "scene2_section": "GENERATIVE AI", "scene2_title": "THE MACHINE LEARNED TO TURN INSTRUCTIONS INTO CREATION", "scene2_narration": "Generative AI changed the interface. Instead of navigating complex software step by step, people describe what they want and get a first version.", "scene2_image": "", "scene2_text_position": "right", "scene2_signal": "CREATE", "scene2_sub": "GEN-AI", "scene2_m1": "TEXT", "scene2_m2": "IMAGE", "scene2_m3": "AUDIO", "scene2_m4": "VIDEO",
        "scene3_section": "AI + WORK", "scene3_title": "THE BIGGEST CHANGE MAY BE AUGMENTATION, NOT AUTOMATION", "scene3_narration": "The most useful AI tools often work beside people: summarizing information, exploring options and writing drafts so humans move faster.", "scene3_image": "", "scene3_text_position": "left", "scene3_signal": "AUGMENT", "scene3_sub": "HUMAN + AI", "scene3_m1": "SPEED", "scene3_m2": "IDEAS", "scene3_m3": "TOOLS", "scene3_m4": "OUTPUT",
        "scene4_section": "THE BIG IDEA", "scene4_title": "AI'S FUTURE DEPENDS ON WHAT HUMANS CHOOSE TO DO WITH IT", "scene4_narration": "Technology creates capabilities, but direction still comes from people. The real question is not only what AI can do, but what is worth doing.", "scene4_image": "", "scene4_text_position": "center", "scene4_signal": "FUTURE", "scene4_sub": "HUMANITY", "scene4_m1": "CHOICE", "scene4_m2": "TRUST", "scene4_m3": "VALUE", "scene4_m4": "IMPACT",
    },
)

AI_DIGITAL_FUTURE = NicheSpec(
    niche="ai_digital_future",
    name="AI — Digital Future (16:9)",
    template_id="15_AI_Digital_Future_16x9",
    aspect_ratio="16:9",
    language="English",
    audience_and_tone="Tech-curious viewers interested in where AI is heading. Forward-looking but grounded; accurate, no hype.",
    intro_fields=(
        Field("kicker", "Small label above the title, in capitals, e.g. AI / DIGITAL FUTURES.", 30),
        Field("title", "Big title in capitals, 2-4 words, e.g. BEYOND HUMAN LIMITS.", 30),
        Field("text", "Keywords line in capitals separated by •, e.g. AGENTS • ROBOTICS • THE NEXT WEB.", 60),
    ),
    # The template draws exactly four progress dots and "01 / 04".
    items=ItemGroup("scene", "scene", 4, 4, (
        Field("section", "Section label in capitals, e.g. AI AGENTS.", 20),
        Field("title", "Headline in capitals, one strong statement.", 80),
        Field("narration", "Narration typed out on screen, 2 sentences.", 210),
        IMAGE,
        POSITION,
        Field("metric", "Panel headline in capitals, one word or year, e.g. AGENTS or 2030+.", 10),
        Field("desc", "Panel subtitle in capitals, e.g. ACTION LOOP.", 14),
        Field("bars", "Seven numbers from 0 to 100 separated by commas, drawn as a bar chart, e.g. 55,70,48,82,64,91,76.", kind="bars"),
    )),
    example={
        "video_id": "AD-001", "publish_at": "",
        "youtube_title": "4 Shifts That Will Define the Next Era of AI",
        "youtube_description": "Generative AI, agents, robotics and the people who adapt.\n#AI #FutureTech #Robotics",
        "youtube_tags": "future of ai, ai agents, robotics, generative ai",
        "intro_kicker": "AI / DIGITAL FUTURES", "intro_title": "BEYOND HUMAN LIMITS.", "intro_text": "GENERATIVE AI • ROBOTICS • AGENTS • THE NEXT WEB",
        "scene1_section": "GENERATIVE AI", "scene1_title": "THE COMPUTER IS LEARNING TO SPEAK THE LANGUAGE OF IDEAS", "scene1_narration": "Generative models made AI feel conversational. A prompt can now become text, an image, a design or a piece of code.", "scene1_image": "", "scene1_text_position": "left", "scene1_metric": "GEN-AI", "scene1_desc": "MULTIMODAL", "scene1_bars": "55,70,48,82,64,91,76",
        "scene2_section": "AI AGENTS", "scene2_title": "THE NEXT STEP IS NOT JUST ANSWERS — IT IS ACTION", "scene2_narration": "AI agents are designed to work through multi-step tasks, use tools and move from answering instructions toward completing workflows.", "scene2_image": "", "scene2_text_position": "right", "scene2_metric": "AGENTS", "scene2_desc": "ACTION LOOP", "scene2_bars": "42,58,72,63,88,75,94",
        "scene3_section": "ROBOTICS", "scene3_title": "WHEN INTELLIGENCE MEETS A BODY, SOFTWARE ENTERS THE REAL WORLD", "scene3_narration": "Robotics connects perception, reasoning and movement. Better AI can give machines a richer understanding of the spaces people move through.", "scene3_image": "", "scene3_text_position": "left", "scene3_metric": "ROBOTICS", "scene3_desc": "REAL WORLD", "scene3_bars": "50,45,67,78,59,84,72",
        "scene4_section": "THE NEXT ERA", "scene4_title": "THE BIGGEST AI BREAKTHROUGH MAY BE HUMAN ADAPTATION", "scene4_narration": "Technology changes faster when people change with it. The advantage will come from working with intelligent systems without losing judgment.", "scene4_image": "", "scene4_text_position": "center", "scene4_metric": "2030+", "scene4_desc": "HUMAN + AI", "scene4_bars": "62,74,69,88,79,93,86",
    },
)

NICHES: Dict[str, NicheSpec] = {s.niche: s for s in (
    FOCUS_HABITS, GEETA_GYAAN, GENERAL_QUIZ, SCIENCE_QUIZ, SCIENCE_STORY,
    INDIAN_TRADITIONAL_STORY, INDIAN_HERITAGE_STORY, CRIME_FILES, AI_NEURAL, AI_DIGITAL_FUTURE,
)}


def get_spec(niche: str) -> NicheSpec:
    if niche not in NICHES:
        raise KeyError(f"Unknown niche '{niche}'. Known: {', '.join(NICHES)}")
    return NICHES[niche]
