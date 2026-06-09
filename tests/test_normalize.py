from kellblog_audio.glossary import apply_glossary
from kellblog_audio.text_clean import (
    clean_for_tts,
    excerpt_from_body,
    normalize_unicode,
)


def test_glossary_saas():
    assert "sass" in apply_glossary("Our SaaS product")


def test_glossary_technical_acronyms():
    spoken = apply_glossary("XML, XQuery, DBMS, RDBMS, OLAP, RFID")

    assert "X M L" in spoken
    assert "X Query" in spoken
    assert "D B M S" in spoken
    assert "R D B M S" in spoken
    assert "O L A P" in spoken
    assert "R F I D" in spoken


def test_glossary_plural_acronyms():
    spoken = apply_glossary("CEOs, VCs, DBMSs, MQLs, CMOs, APIs")

    assert "C E O's" in spoken
    assert "V C's" in spoken
    assert "D B M S's" in spoken
    assert "M Q L's" in spoken
    assert "C M O's" in spoken
    assert "A P I's" in spoken


def test_glossary_expands_catalog_pronunciation_terms():
    spoken = apply_glossary(
        "SaaStr SaaStock MarkLogic NoSQL DB2 EIR PR UK EMEA QBR SEC HR EV "
        "IPOs CFOs CPOs RevOps S1 S-1 R40 NTM BANT"
    )

    assert "sass-ter" in spoken
    assert "sass stock" in spoken
    assert "Mark Logic" in spoken
    assert "No S Q L" in spoken
    assert "D B two" in spoken
    assert "E I R" in spoken
    assert "P R" in spoken
    assert "U K" in spoken
    assert "E M E A" in spoken
    assert "Q B R" in spoken
    assert "S E C" in spoken
    assert "H R" in spoken
    assert "E V" in spoken
    assert "I P O's" in spoken
    assert "C F O's" in spoken
    assert "C P O's" in spoken
    assert "Rev Ops" in spoken
    assert "S one" in spoken
    assert "Rule of 40" in spoken
    assert "N T M" in spoken
    assert "B A N T" in spoken


def test_glossary_expands_second_pass_business_terms():
    spoken = apply_glossary(
        "NDR EBITDA SMB CSM CSMs TAM SEO QCR QCRs SC SCs SVP MDM CTO FCF "
        "COVID GRR SVB PEG CSAT MBAs ACV CMMI IDC AEs PMs ETL T2D3 CTA "
        "COGS RPO CDO CDOs PMF RAG QED TCO RSUs IP DEVs CXOs ACID GMs "
        "ISO IMHO OTE A16Z"
    )

    assert "N D R" in spoken
    assert "E B I T D A" in spoken
    assert "S M B" in spoken
    assert "C S M" in spoken
    assert "C S M's" in spoken
    assert "T A M" in spoken
    assert "S E O" in spoken
    assert "Q C R" in spoken
    assert "Q C R's" in spoken
    assert "S C" in spoken
    assert "S C's" in spoken
    assert "S V P" in spoken
    assert "M D M" in spoken
    assert "C T O" in spoken
    assert "F C F" in spoken
    assert "COVID" not in spoken
    assert "G R R" in spoken
    assert "S V B" in spoken
    assert "P E G" in spoken
    assert "C SAT" in spoken
    assert "M B A's" in spoken
    assert "A C V" in spoken
    assert "C M M I" in spoken
    assert "I D C" in spoken
    assert "A E's" in spoken
    assert "P M's" in spoken
    assert "E T L" in spoken
    assert "T two D three" in spoken
    assert "C T A" in spoken
    assert "C O G S" in spoken
    assert "R P O" in spoken
    assert "C D O" in spoken
    assert "C D O's" in spoken
    assert "P M F" in spoken
    assert "R A G" in spoken
    assert "Q E D" in spoken
    assert "T C O" in spoken
    assert "R S U's" in spoken
    assert "I P" in spoken
    assert "devs" in spoken
    assert "C X O's" in spoken
    assert "acid" in spoken
    assert "G M's" in spoken
    assert "I S O" in spoken
    assert "I M H O" in spoken
    assert "O T E" in spoken
    assert "A sixteen Z" in spoken


def test_glossary_expands_third_pass_catalog_terms():
    spoken = apply_glossary(
        "OK HIT MISS ASK II III ASC FP KM CG CA MVP C3 ERG VC1 VC2 FAST "
        "DC PS G2 GE IC SOX T25 CCS MM"
    )

    assert "okay" in spoken
    assert "hit" in spoken
    assert "miss" in spoken
    assert "ask" in spoken
    assert "two" in spoken
    assert "three" in spoken
    assert "A S C" in spoken
    assert "F P" in spoken
    assert "K M" in spoken
    assert "C G" in spoken
    assert "California" in spoken
    assert "M V P" in spoken
    assert "C three" in spoken
    assert "E R G" in spoken
    assert "V C one" in spoken
    assert "V C two" in spoken
    assert "Fast" in spoken
    assert "D C" in spoken
    assert "P S" in spoken
    assert "G two" in spoken
    assert "G E" in spoken
    assert "I C" in spoken
    assert "socks" in spoken
    assert "T twenty five" in spoken
    assert "C C S" in spoken
    assert "M M" in spoken


def test_glossary_embedded_technical_terms():
    spoken = apply_glossary("pureXML XMLQUERY DBMS2 DBMSroulette RDBMSweb XPath")

    assert "pure X M L" in spoken
    assert "X M L Query" in spoken
    assert "D B M S two" in spoken
    assert "D B M S roulette" in spoken
    assert "R D B M S web" in spoken
    assert "X Path" in spoken


def test_normalize_smart_quotes():
    assert '"' in normalize_unicode("\u201chello\u201d")


def test_clean_for_tts_does_not_say_next_for_bullets():
    cleaned = clean_for_tts("<ul><li>First point</li><li>Second point</li></ul>")

    assert "Next" not in cleaned
    assert "First point" in cleaned
    assert "Second point" in cleaned


def test_clean_for_tts_replaces_raw_urls_with_link_phrase():
    cleaned = clean_for_tts(
        "See https://www.kellblog.com/foo/ and www.example.com/bar for details."
    )

    assert "https://" not in cleaned
    assert "www." not in cleaned
    assert "linked page" in cleaned


def test_clean_for_tts_expands_abbreviations_and_slashes():
    cleaned = clean_for_tts(
        "This market / technology problem includes e.g., BLOBs and CLOBs, i.e., old approaches."
    )

    assert "market slash technology" in cleaned
    assert "for example" in cleaned
    assert "that is" in cleaned
    assert "blobs" in cleaned
    assert "clobs" in cleaned
    assert "e.g." not in cleaned
    assert "i.e." not in cleaned


def test_clean_for_tts_removes_dots_from_initialisms():
    cleaned = clean_for_tts(
        "The U.S. team met at 3 A.M. with H.L. Mencken and C. K. Prahalad about I.T."
    )

    assert "U S team" in cleaned
    assert "3 A M" in cleaned
    assert "H L Mencken" in cleaned
    assert "C K Prahalad" in cleaned
    assert "I T" in cleaned
    assert "U.S." not in cleaned
    assert "A.M." not in cleaned


def test_clean_for_tts_repairs_legacy_import_artifacts():
    cleaned = clean_for_tts(
        "It' s fascinating. While I've been at Mark Logic for year, "
        "the government has a pre-attachment to XML. "
        "They have all start to show interest in the category for application such as flight manuals. "
        "OLAP servers (nee MD-DBMSs) and indexing products (e.g., bitmap indexing a la Sybase IQ)."
    )

    assert "It's fascinating" in cleaned
    assert "for a year" in cleaned
    assert "predilection for X M L" in cleaned
    assert "have all started to show interest" in cleaned
    assert "applications such as flight manuals" in cleaned
    assert "formerly called multidimensional database management systems" in cleaned
    assert "such as Sybase I Q" in cleaned
    assert "pre-attachment" not in cleaned
    assert "start to show" not in cleaned
    assert "MD-D" not in cleaned
    assert "a la" not in cleaned


def test_clean_for_tts_handles_lowercase_dotted_abbreviations():
    cleaned = clean_for_tts(
        "Quota Club (a.k.a. President's Club) starts at 2:10 a.m. and ends by 5 p.m."
    )

    assert "also known as President's Club" in cleaned
    assert "2:10 A M" in cleaned
    assert "5 P M" in cleaned
    assert "a.k.a." not in cleaned
    assert "a.m." not in cleaned
    assert "p.m." not in cleaned


def test_clean_for_tts_handles_multidimensional_dbms_terms():
    cleaned = clean_for_tts(
        "A shift from MD-DBMS to OLAP and from MD-DBMSs to analytic databases."
    )

    assert "multidimensional database management system to O L A P" in cleaned
    assert (
        "multidimensional database management systems to analytic databases" in cleaned
    )
    assert "MD-D" not in cleaned


def test_clean_for_tts_verbalizes_audio_symbols_and_shorthand():
    cleaned = clean_for_tts(
        "Jason & crew held SaaStr Annual @ Home after raising $50M. "
        "The company grew 40%, took 4-6 years, spent 10M/year, "
        "tracked EV/NTM, sales/marketing, and/or LTV/CAC."
    )

    assert "Jason and crew" in cleaned
    assert "Annual at Home" in cleaned
    assert "50 million dollars" in cleaned
    assert "40 percent" in cleaned
    assert "4 to 6 years" in cleaned
    assert "10 million per year" in cleaned
    assert "E V slash N T M" in cleaned
    assert "sales slash marketing" in cleaned
    assert "and or" in cleaned
    assert "L T V slash C A C" in cleaned
    assert "&" not in cleaned
    assert "@" not in cleaned
    assert "$" not in cleaned
    assert "%" not in cleaned


def test_clean_for_tts_handles_trillions_and_three_part_ranges():
    cleaned = clean_for_tts("The plan promised $1T and a 1-1-1 model.")

    assert "1 trillion dollars" in cleaned
    assert "1 to 1 to 1 model" in cleaned
    assert "$" not in cleaned
    assert "1-1" not in cleaned


def test_clean_for_tts_handles_legacy_finance_amount_shorthand():
    cleaned = clean_for_tts(
        "The median is $13MM, exits are $150bn, burn is $20mm, "
        "software cost $10s of millions, and Stance raised $116in VC."
    )

    assert "13 million dollars" in cleaned
    assert "150 billion dollars" in cleaned
    assert "20 million dollars" in cleaned
    assert "tens of millions of dollars" in cleaned
    assert "116 million dollars in V C" in cleaned
    assert "$" not in cleaned


def test_clean_for_tts_verbalizes_remaining_inline_symbols():
    cleaned = clean_for_tts(
        "R&D and S&M made us #1 after @OnlyCFO showed that 0.9^2 beats 0.9^3."
    )

    assert "R and D" in cleaned
    assert "S and M" in cleaned
    assert "number 1" in cleaned
    assert "at Only C F O" in cleaned
    assert "0.9 squared" in cleaned
    assert "0.9 cubed" in cleaned
    assert "&" not in cleaned
    assert "@" not in cleaned
    assert "#" not in cleaned
    assert "^" not in cleaned


def test_clean_for_tts_verbalizes_symbols_inside_tokens_and_generic_exponents():
    cleaned = clean_for_tts("O L A P@Work used A&B plus A)&(B and (1-churn)^N.")

    assert "O L A P at Work" in cleaned
    assert "A and B" in cleaned
    assert "A) and (B" in cleaned
    assert "to the N" in cleaned
    assert "&" not in cleaned
    assert "@" not in cleaned
    assert "^" not in cleaned


def test_clean_for_tts_repairs_extraction_joins_and_download_filenames():
    cleaned = clean_for_tts(
        '"Famous Last WordsI can tell." -- Bruce SpringsteenThe River. '
        "Theodore LevittAt some point. Stephen Wright (comedian)Much as. "
        "Download USS_Nimitz_%28CVN-68%29_general_quarters_drill%2C_ca._2013.oga"
    )

    assert "Famous Last Words. I can tell." in cleaned
    assert "Bruce Springsteen. The River." in cleaned
    assert "Theodore Levitt. At some point." in cleaned
    assert "Stephen Wright (comedian). Much as." in cleaned
    assert "Download the linked file" in cleaned
    assert "WordsI" not in cleaned
    assert "SpringsteenThe" not in cleaned
    assert "LevittAt" not in cleaned
    assert "USS_Nimitz" not in cleaned
    assert "%28" not in cleaned


def test_excerpt_truncates():
    long = "Word. " * 200
    ex = excerpt_from_body(long, max_chars=100)
    assert len(ex) <= 105
    assert ex.endswith("…") or len(ex) <= 100
