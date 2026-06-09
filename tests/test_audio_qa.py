from kellblog_audio.qa import analyze_transcript


def test_analyze_transcript_passes_matching_audio_text():
    source = " ".join(f"word{i}" for i in range(120))
    transcript = "Intro words. " + source + " Outro words."

    result = analyze_transcript(source, transcript, duration_sec=60)

    assert result.passed
    assert result.source_coverage >= 0.95


def test_analyze_transcript_strips_known_intro_and_outro():
    source = " ".join(f"word{i}" for i in range(120))
    intro = "This is the known intro."
    outro = "This is the known outro."
    transcript = f"{intro} {source} {outro}"

    result = analyze_transcript(
        source,
        transcript,
        duration_sec=60,
        intro_text=intro,
        outro_text=outro,
    )

    assert result.source_coverage == 1.0
    assert result.tail_similarity == 1.0
    assert result.transcript_words == 120


def test_tail_similarity_checks_every_possible_window():
    source_words = [f"word{i}" for i in range(120)]
    source = " ".join(source_words)
    transcript = "lead " + " ".join(source_words[-80:]) + " outro"

    result = analyze_transcript(source, transcript)

    assert result.tail_similarity == 1.0


def test_analyze_transcript_fails_truncated_audio_text():
    source_words = [f"word{i}" for i in range(120)]
    source = " ".join(source_words)
    transcript = " ".join(source_words[:50])

    result = analyze_transcript(source, transcript, duration_sec=60)

    assert not result.passed
    assert "coverage" in result.reason


def test_analyze_transcript_fails_excess_repetition():
    source = " ".join(f"word{i}" for i in range(120))
    repeated = "bad loop phrase " * 20
    transcript = source[:300] + " " + repeated + " " + source[-300:]

    result = analyze_transcript(source, transcript, duration_sec=60)

    assert not result.passed
    assert "repetition" in result.reason


def test_analyze_transcript_matches_spelled_and_joined_acronyms():
    source = "X M L content uses D B M S, R D B M S, and S Q L systems."
    transcript = "XML content uses DBMS, RDBMS, and SQL systems."

    result = analyze_transcript(source, transcript)

    assert result.passed
    assert result.source_coverage == 1.0
