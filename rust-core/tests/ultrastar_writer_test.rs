//! Testes de integração do ultrastar_writer, usando um fixture baseado em
//! dados reais de teste ("Sangue Latino", validado manualmente no
//! UltraStar Deluxe/Play em 05/07/2026) para garantir que a portabilidade
//! Python -> Rust preserva o comportamento correto, incluindo os bugs já
//! corrigidos do lado Python (BPM bruto, #VERSION, quebras de frase,
//! espaçamento de sílabas).

use uskmaker_core::Song;

fn load_fixture() -> Song {
    Song::from_json_file("tests/fixtures/sample_song.json")
        .expect("deveria carregar o fixture de teste (tests/fixtures/sample_song.json)")
}

#[test]
fn parses_json_and_generates_valid_header() {
    let song = load_fixture();
    let txt = song.to_txt();

    assert!(
        txt.starts_with("#VERSION:1.0.0\n#TITLE:Sangue Latino\n#ARTIST:Rita Lee\n"),
        "header deve começar com VERSION, TITLE, ARTIST nessa ordem.\nSaída real:\n{}",
        txt
    );
    assert!(txt.contains("#MP3:Rita Lee - Sangue Latino.ogg\n"));
    // #AUDIO duplica o #MP3 de propósito: a spec v1 manda desconsiderar o
    // #MP3 quando o #AUDIO existe, e na v2 o #AUDIO vira core. Os dois
    // apontam para o MESMO arquivo - se um dia divergirem, é bug.
    assert!(txt.contains("#AUDIO:Rita Lee - Sangue Latino.ogg\n"));
    // #VOCALS/#INSTRUMENTAL são OPCIONAIS (opt-in do usuário): quando não
    // vieram no JSON, não podem aparecer no .txt apontando pra arquivo
    // nenhum - um header quebrado é pior que header ausente.
    assert!(!txt.contains("#VOCALS:"), "sem stems no JSON => sem header");
    assert!(!txt.contains("#INSTRUMENTAL:"));
    // BPM BRUTO, sem multiplicação por 4 - o bug histórico que causava
    // dessincronia de 4x (ver notas em ultrastar_writer.rs e no
    // beatgrid.py do lado Python).
    assert!(txt.contains("#BPM:123.05\n"), "BPM deve ser o valor bruto (123.05), não multiplicado por 4");
    assert!(txt.contains("#GAP:0\n"));
    assert!(txt.contains("#LANGUAGE:pt\n"));
    assert!(txt.contains("#CREATOR:USKMaker\n"));
}

#[test]
fn preserves_negative_pitch_and_continuation_syllables() {
    let song = load_fixture();
    let txt = song.to_txt();

    // Pitch negativo (nota abaixo de C4) deve ser preservado como está
    assert!(txt.contains(": 266 2 -3 Ju\n"), "pitch negativo não preservado.\n{}", txt);

    // Sílaba de continuação com "~" e espaço à direita (fim de palavra)
    assert!(
        txt.contains(": 268 3 -1 ~rei \n"),
        "convenção de espaçamento (~  + espaço no fim da palavra) não preservada.\n{}",
        txt
    );
}

#[test]
fn preserves_freestyle_note_type() {
    let song = load_fixture();
    let txt = song.to_txt();

    assert!(
        txt.contains("F 471 1 0 é \n"),
        "nota tipo F (freestyle, baixa confiança de pitch) não preservada.\n{}",
        txt
    );
}

#[test]
fn inserts_phrase_break_marker_at_correct_position() {
    let song = load_fixture();
    let txt = song.to_txt();

    // phrase_breaks_after_index: [1] -> quebra depois da nota "~rei "
    // (índice 1), com o beat da PRÓXIMA nota (índice 2, start_beat=271)
    assert!(
        txt.contains("~rei \n- 271\n"),
        "marcador de quebra de frase ausente ou na posição errada.\n{}",
        txt
    );
}

#[test]
fn ends_with_e_marker() {
    let song = load_fixture();
    let txt = song.to_txt();
    assert!(txt.trim_end().ends_with('E'), "arquivo deve terminar com a linha 'E'");
}

#[test]
fn detects_forced_overlap() {
    let mut song = load_fixture();
    // força um overlap manualmente para testar o detector
    song.notes[0].duration_beats = 100;
    let warnings = song.validate_no_overlap();
    assert!(!warnings.is_empty(), "deveria detectar overlap forçado (nota 0 estendida além da nota 1)");
}

#[test]
fn no_overlap_in_clean_fixture() {
    let song = load_fixture();
    let warnings = song.validate_no_overlap();
    assert!(
        warnings.is_empty(),
        "fixture não deveria ter overlaps, mas encontrou: {:?}",
        warnings
    );
}

#[test]
fn duet_writes_p1_p2_headers_and_two_blocks() {
    let mut song = load_fixture();
    song.duet = true;
    song.p1_name = Some("Elton".to_string());
    song.p2_name = Some("Kiki".to_string());
    // atribui cantores: nota 0 -> P1, nota 1 -> ambos, nota 2 -> P2
    song.notes[0].singer = 1;
    song.notes[1].singer = 3;
    song.notes[2].singer = 2;
    for n in song.notes.iter_mut().skip(3) {
        n.singer = 1;
    }
    let txt = song.to_txt();

    // headers de dueto, na convenção da comunidade (#P1/#P2), entre ARTIST e MP3
    assert!(txt.contains("#ARTIST:Rita Lee\n#P1:Elton\n#P2:Kiki\n#MP3:"),
            "headers de dueto ausentes ou fora de posição.\n{}", txt);
    // corpo em dois blocos
    let p1 = txt.find("\nP1\n").expect("bloco P1 ausente");
    let p2 = txt.find("\nP2\n").expect("bloco P2 ausente");
    assert!(p1 < p2, "P1 deve vir antes de P2");
    // a nota "ambos" (índice 1) aparece nos DOIS blocos
    let both_line = format!(
        "{} {} {} {} {}",
        song.notes[1].note_type, song.notes[1].start_beat,
        song.notes[1].duration_beats, song.notes[1].pitch, song.notes[1].text
    );
    assert_eq!(txt.matches(&both_line).count(), 2,
               "nota 'ambos' deveria aparecer nos dois blocos.\n{}", txt);
    // a nota só-P2 (índice 2) NÃO aparece no bloco P1
    let p2_only = format!(
        "{} {} {} {} {}",
        song.notes[2].note_type, song.notes[2].start_beat,
        song.notes[2].duration_beats, song.notes[2].pitch, song.notes[2].text
    );
    let p1_block = &txt[p1..p2];
    assert!(!p1_block.contains(&p2_only),
            "nota exclusiva do P2 vazou pro bloco P1.\n{}", p1_block);
    assert!(txt.trim_end().ends_with('E'), "um único 'E' no fim");
}

#[test]
fn solo_output_unchanged_without_duet_flag() {
    // regressão: sem duet, nada de #P1/#P2 nem marcadores P1/P2
    let song = load_fixture();
    let txt = song.to_txt();
    assert!(!txt.contains("#P1:"), "solo não pode ter #P1");
    assert!(!txt.contains("\nP1\n"), "solo não pode ter bloco P1");
}

#[test]
fn format_number_matches_python_convention() {
    // Espelha exatamente Song._format_number do python-sidecar:
    // inteiro exato -> sem decimais; senão -> sempre 2 casas decimais.
    assert_eq!(Song::format_number(123.0), "123");
    assert_eq!(Song::format_number(123.05), "123.05");
    assert_eq!(Song::format_number(492.20), "492.20");
    assert_eq!(Song::format_number(0.0), "0");
}
