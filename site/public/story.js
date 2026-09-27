/* Tonight's film, "Luna and the Lamp", as a Lanternist storyboard: the cast, the place and seven
 * shots in four paragraphs. It grows from the line the app's voice samples open with (`text.SAMPLES`):
 * a small grey cat in a lighthouse by the sea. Narration is in the story's language; the picture and
 * sound prompts are English, as in the app. The shots' paper sets are in scenes.js, in the same order.
 * The app's facts copied here (speeds, languages, seeds) are checked against it by tests/test_site.py. */

/** Narration speed by language, words a minute (`writer.WPM`). */
export const WPM = {
  en: 150,
  es: 140,
  pt: 140,
  fr: 145,
  it: 145,
  de: 130,
  ru: 125,
  zh: 240,
  ja: 240,
  ko: 170,
};

export const LANGUAGES = {
  en: "English",
  es: "Español",
  pt: "Português",
  fr: "Français",
  de: "Deutsch",
  it: "Italiano",
  ru: "Русский",
  zh: "中文",
  ja: "日本語",
  ko: "한국어",
};

/** Words as the app counts them for timing (`text.word_count`): CJK characters count as half a word. */
export function words(text) {
  const cjk = (text.match(/[぀-ヿ㐀-鿿가-힯]/g) || []).length;
  return (text.match(/[\p{L}\p{N}_]+/gu) || []).length + Math.floor(cjk / 2);
}

export const seconds = (text, lang) => (words(text) / WPM[lang]) * 60;

export const TITLE = { en: "Luna and the Lamp", es: "Luna y la lámpara", pt: "Luna e a lâmpada" };

export const CAST = [
  { id: "luna", name: "Luna", kind: "character", look: "a small grey cat with amber eyes and a pale chest" },
  {
    id: "tomas",
    name: "Tomás",
    kind: "character",
    look: "an old lighthouse keeper with a white beard, a yellow oilskin coat and a sou'wester",
  },
  {
    id: "marisol",
    name: "the Marisol",
    kind: "object",
    look: "a little red fishing boat with a cream stripe and a lantern on its mast",
  },
];

export const PLACE = {
  id: "lighthouse",
  name: "the lighthouse",
  look: "a cream lighthouse with red bands on a black rock",
};

export const SHOTS = [
  {
    n: 1,
    shot: "wide",
    mode: "video",
    camera: "push_in",
    continues: false,
    cast: ["luna"],
    place: "lighthouse",
    visual:
      "Wide shot at night: the lighthouse on its black rock above a calm sea, its beam sweeping the dark; a small cat's silhouette in one lit window.",
    motion: "The beam turns slowly; the waves roll; the paper stars swing on their threads.",
    sound: "a calm sea, soft wind",
    narration: {
      en: "On a rock at the edge of the sea stood a lighthouse, and in it lived a small grey cat called Luna.",
      es: "En una roca, a la orilla del mar, había un faro, y en él vivía una gatita gris llamada Luna.",
      pt: "Numa rocha, à beira do mar, havia um farol, e nele morava uma gatinha cinza chamada Luna.",
      fr: "Sur un rocher, au bord de la mer, se dressait un phare, et dans ce phare vivait une petite chatte grise nommée Luna.",
      de: "Auf einem Felsen am Rand des Meeres stand ein Leuchtturm, und darin wohnte eine kleine graue Katze namens Luna.",
      it: "Su uno scoglio, in riva al mare, c'era un faro, e nel faro viveva una gattina grigia di nome Luna.",
      ru: "На скале у самого моря стоял маяк, и жила в нём маленькая серая кошка по имени Луна.",
      zh: "在海边的一块礁石上，矗立着一座灯塔，灯塔里住着一只名叫露娜的灰色小猫。",
      ja: "海のはしの岩の上に灯台が立っていて、そこにはルナという小さな灰色のねこが住んでいました。",
      ko: "바닷가 바위 위에 등대가 하나 서 있었고, 그 안에는 루나라는 작은 회색 고양이가 살았어요.",
    },
  },
  {
    n: 2,
    shot: "close",
    mode: "still",
    camera: "push_in",
    continues: true,
    cast: ["tomas", "luna"],
    place: "lighthouse",
    visual:
      "Close shot inside the lamp room: Tomás lifts a lit taper to the great brass lamp; Luna sleeps curled in the warm circle of light on the floor.",
    motion: "The flame flickers; Luna breathes slowly in her sleep.",
    sound: "a crackling wick, the sea far below",
    narration: {
      en: "Every night, old Tomás lit the great lamp, and Luna slept in its warm circle. She loved the light. She did not love the dark.",
      es: "Cada noche, el viejo Tomás encendía la gran lámpara, y Luna dormía en su círculo tibio. Amaba la luz. No amaba la oscuridad.",
      pt: "Toda noite, o velho Tomás acendia a grande lâmpada, e Luna dormia no seu círculo morno. Ela amava a luz. Não amava o escuro.",
      fr: "Chaque soir, le vieux Tomás allumait la grande lampe, et Luna dormait dans son cercle tiède. Elle aimait la lumière. Elle n'aimait pas le noir.",
      de: "Jeden Abend zündete der alte Tomás die große Lampe an, und Luna schlief in ihrem warmen Lichtkreis. Sie liebte das Licht. Die Dunkelheit liebte sie nicht.",
      it: "Ogni sera il vecchio Tomás accendeva la grande lampada, e Luna dormiva nel suo cerchio tiepido. Amava la luce. Non amava il buio.",
      ru: "Каждый вечер старый Томас зажигал большую лампу, и Луна спала в её тёплом круге. Она любила свет. Темноту она не любила.",
      zh: "每天晚上，老托马斯都会点亮那盏大灯，露娜就睡在它温暖的光圈里。她喜欢光。她不喜欢黑暗。",
      ja: "毎晩、トマスじいさんが大きなランプをともすと、ルナはそのあたたかな光の輪の中で眠りました。ルナは光が大好きでした。でも、暗やみは好きではありませんでした。",
      ko: "밤마다 토마스 할아버지가 커다란 등불을 켜면, 루나는 그 따스한 빛 동그라미 안에서 잠들었어요. 루나는 빛을 좋아했어요. 어둠은 좋아하지 않았어요.",
    },
  },
  {
    n: 3,
    shot: "wide",
    mode: "video",
    camera: "static",
    continues: false,
    cast: [],
    place: "lighthouse",
    visual:
      "Wide shot in a storm: rain and lightning over a heaving sea; the lighthouse's lamp gutters and goes out.",
    motion: "Rain sweeps across; the waves heave; the lamp flickers, then dies.",
    sound: "a storm: heavy rain, gusting wind, rolling thunder",
    narration: {
      en: "One stormy night, the wind blew the great lamp out. Tomás was down in the village, and the tower went black.",
      es: "Una noche de tormenta, el viento apagó la gran lámpara. Tomás estaba en el pueblo, y la torre quedó a oscuras.",
      pt: "Numa noite de tempestade, o vento apagou a grande lâmpada. Tomás estava na vila, e a torre ficou às escuras.",
    },
  },
  {
    n: 4,
    shot: "wide",
    mode: "video",
    camera: "static",
    continues: true,
    cast: ["marisol"],
    place: "",
    visual:
      "Wide shot on the open sea at night: the Marisol tossed between big waves, the dark lighthouse far away on the horizon.",
    motion: "The boat pitches and rolls; its lantern swings; rain falls.",
    sound: "big waves, rain on the water, a creaking hull",
    narration: {
      en: "Far out on the water, a little red boat was looking for its way home.",
      es: "Lejos, sobre el agua, un barquito rojo buscaba el camino a casa.",
      pt: "Lá longe, sobre a água, um barquinho vermelho procurava o caminho de casa.",
    },
  },
  {
    n: 5,
    shot: "close",
    mode: "video",
    camera: "static",
    continues: false,
    cast: ["luna"],
    place: "lighthouse",
    visual:
      "Close shot on the tower's stairs in the dark: Luna climbs, one step at a time; a small window flickers with lightning.",
    motion: "Luna hops up one step at a time; the window flashes.",
    sound: "rain against stone, wind in the tower",
    narration: {
      en: "Luna's paws shook. The stairs went up and up into the dark. She climbed anyway, one step at a time, counting them like stars.",
      es: "A Luna le temblaban las patas. La escalera subía y subía hacia la oscuridad. Aun así, subió, un escalón a la vez, contándolos como estrellas.",
      pt: "As patas de Luna tremiam. A escada subia e subia para dentro do escuro. Mesmo assim, ela subiu, um degrau de cada vez, contando-os como estrelas.",
    },
  },
  {
    n: 6,
    shot: "close",
    mode: "video",
    camera: "static",
    continues: true,
    cast: ["luna", "marisol"],
    place: "lighthouse",
    visual:
      "Close shot in the dark lamp room: only Luna's eyes shine gold; through the window, the little boat turns towards the rock.",
    motion: "Lightning flashes; Luna's eyes blaze; far out, the boat turns for home.",
    sound: "rain on glass, distant thunder",
    narration: {
      en: "At the top, her eyes caught the lightning and shone like two small lamps. Out at sea, the little boat saw them, and turned for home.",
      es: "Arriba, sus ojos atraparon el relámpago y brillaron como dos lamparitas. En el mar, el barquito los vio y puso rumbo a casa.",
      pt: "Lá em cima, seus olhos pegaram o brilho do relâmpago e brilharam como duas lamparinas. No mar, o barquinho os viu e voltou para casa.",
    },
  },
  {
    n: 7,
    shot: "wide",
    mode: "still",
    camera: "pull_out",
    continues: false,
    cast: ["tomas", "luna", "marisol"],
    place: "lighthouse",
    visual:
      "Medium shot on the gallery at dawn: Tomás smiles down at Luna, curled beside the lamp; the Marisol is moored below, gulls overhead.",
    motion: "Gulls wheel; the sun climbs; the sea is calm.",
    sound: "a calm morning sea, gulls",
    narration: {
      en: "In the morning, Tomás found her curled beside the lamp. Luna still loves the light. But now she knows the dark is only a place where a little light is needed.",
      es: "Por la mañana, Tomás la encontró acurrucada junto a la lámpara. Luna todavía ama la luz. Pero ahora sabe que la oscuridad es solo un lugar donde hace falta un poco de luz.",
      pt: "De manhã, Tomás a encontrou enroladinha ao lado da lâmpada. Luna ainda ama a luz. Mas agora sabe que o escuro é só um lugar onde falta um pouquinho de luz.",
    },
  },
];

/** A re-roll's seed, as the app makes it (`storyboard.next_seed`). */
export const nextSeed = (seed) => (seed * 7919 + 104729) % 999983;
export const SEED = 7;

/**
 * Subtitle cues for one shot: whole sentences, split again on commas past 90 characters
 * (`text.MAX_CUE`), each on screen for its share of the shot.
 */
export function cues(text) {
  const out = [];
  for (const sentence of text.match(/[^.!?。！？]+[.!?。！？]*/g) || [text]) {
    let line = "";
    for (const part of sentence.trim().split(/(?<=[,，、])\s*/)) {
      if (line && (line + " " + part).length > 90) {
        out.push(line);
        line = part;
      } else line = line ? `${line} ${part}` : part;
    }
    if (line) out.push(line);
  }
  return out;
}
