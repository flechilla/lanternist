/* "The Little Red Brick", the story this page builds, as a Lanternist storyboard: a cast, a place and
 * eight shots in four paragraphs, each paragraph cut on its sentences into two shots. Narration is in
 * the story's language (English, Spanish, Portuguese); the notes for the pictures, the motion and the
 * sound are English, as the app writes them. The words a minute each language is read at come from
 * the app, through ../story.js, which tests/test_site.py keeps in step. */

import { WPM, words } from "../story.js";

export const TITLE = {
  en: "The Little Red Brick",
  es: "El ladrillito rojo",
  pt: "O tijolinho vermelho",
};

export const CAST = [
  {
    id: "brick",
    name: "the little red brick",
    look: "a small red toy brick, two studs long, with a printed face",
  },
  { id: "pickle", name: "Pickle", look: "a big, soft, sleepy dog with a honey coat and floppy brown ears" },
  {
    id: "rocket",
    name: "the rocket",
    look: "a toy rocket of white, red and blue bricks, one brick short at the top",
  },
];

export const PLACE = {
  id: "playroom",
  name: "the playroom",
  look: "a sunny playroom: a table by the window, a rug, a sofa",
};

export const SHOTS = [
  {
    n: 1,
    shot: "wide",
    mode: "video",
    camera: "push_in",
    continues: false,
    cast: ["brick", "rocket"],
    visual:
      "Wide shot of a sunny playroom table by a window: toy bricks hop into place on a half-built rocket; a little red brick watches from the side.",
    motion: "Bricks hop up and click into the rocket one at a time; clouds drift past the window.",
    sound: "a quiet room, bricks clicking",
    narration: {
      en: "Up on the playroom table, the bricks were building a rocket, with round windows and a bright red nose.",
      es: "Sobre la mesa del cuarto de juegos, los ladrillitos construían un cohete, con ventanas redondas y la punta roja y brillante.",
      pt: "Em cima da mesa do quarto de brinquedos, os tijolinhos montavam um foguete, com janelas redondas e o bico vermelho e brilhante.",
    },
  },
  {
    n: 2,
    shot: "close",
    mode: "still",
    camera: "push_in",
    continues: true,
    cast: ["brick"],
    visual:
      "Close shot at the edge of the table: the little red brick teeters over the drop, eyes wide, the floor far below.",
    motion: "The brick wobbles on the edge, slips, and tumbles out of sight.",
    sound: "a wobble, a clatter far below",
    narration: {
      en: "But one little red brick slipped, bounced off the edge, and tumbled all the way down to the floor.",
      es: "Pero un ladrillito rojo resbaló, rebotó en el borde y cayó rodando hasta el suelo.",
      pt: "Mas um tijolinho vermelho escorregou, quicou na beirada e caiu rolando até o chão.",
    },
  },
  {
    n: 3,
    shot: "wide",
    mode: "video",
    camera: "static",
    continues: false,
    cast: ["brick", "pickle"],
    visual:
      "Wide shot on the floor at toy height: a striped rug, a big sofa behind, Pickle the dog asleep on the rug; the little red brick hops past her nose.",
    motion: "The brick hops across the rug; Pickle breathes slowly in her sleep.",
    sound: "a snoring dog, a ticking clock",
    narration: {
      en: "The floor was enormous. The little brick hopped across the rug, past Pickle the dog, who was fast asleep.",
      es: "El suelo era enorme. El ladrillito cruzó la alfombra a saltitos, junto a Pickle, la perrita, que dormía profundamente.",
      pt: "O chão era enorme. O tijolinho atravessou o tapete aos pulinhos, passando pela Pickle, a cachorrinha, que dormia profundamente.",
    },
  },
  {
    n: 4,
    shot: "wide",
    mode: "video",
    camera: "static",
    continues: true,
    cast: ["brick"],
    visual:
      "Wide shot on the floor: a robot vacuum rolls past a fluffy pink slipper; the little red brick peeks out from inside it.",
    motion: "The vacuum whirs across the floor; the slipper shakes; the brick peeks out.",
    sound: "a whirring robot vacuum",
    narration: {
      en: "Then something whirred. The robot vacuum! The little brick dived into a slipper and waited for the whirring to stop.",
      es: "De pronto, algo zumbó. ¡La aspiradora robot! El ladrillito se metió en una pantufla y esperó a que el zumbido parara.",
      pt: "De repente, algo zumbiu. O aspirador robô! O tijolinho pulou dentro de um chinelo e esperou o zumbido parar.",
    },
  },
  {
    n: 5,
    shot: "wide",
    mode: "still",
    camera: "pull_out",
    continues: false,
    cast: ["brick", "rocket"],
    visual:
      "Low wide shot from the floor: the table's legs tower up to the tabletop far above, the rocket's red nose just showing over the edge; the tiny brick looks up.",
    motion: "The brick leans back to look up, and up.",
    sound: "a quiet room",
    narration: {
      en: "Now the table looked so high. The little brick looked up, and up, and up.",
      es: "Ahora la mesa se veía altísima. El ladrillito miró hacia arriba, y arriba, y arriba.",
      pt: "Agora a mesa parecia altíssima. O tijolinho olhou para cima, e para cima, e para cima.",
    },
  },
  {
    n: 6,
    shot: "close",
    mode: "video",
    camera: "static",
    continues: true,
    cast: ["brick", "pickle"],
    visual:
      "Close shot: Pickle lowers her big soft nose to the floor; the little red brick hops on, and she stretches up towards the tabletop.",
    motion: "Pickle's head dips down, the brick hops onto her nose, and her head rises up and up.",
    sound: "a big yawn, a dog's tags jingling",
    narration: {
      en: "“Need a lift?” yawned Pickle. She lowered her big soft nose, then up she stretched, all the way to the top.",
      es: "—¿Te subo? —bostezó Pickle. Bajó su gran nariz suave y luego se estiró, se estiró, hasta llegar arriba.",
      pt: "— Quer uma carona? — bocejou a Pickle. Ela abaixou o narizão macio e depois se esticou toda, até lá em cima.",
    },
  },
  {
    n: 7,
    shot: "close",
    mode: "video",
    camera: "static",
    continues: false,
    cast: ["brick", "rocket"],
    visual:
      "Close shot of the rocket's top: a gap two studs long; the little red brick hops from Pickle's nose into it.",
    motion: "The brick hops into the gap, wiggles, and clicks into place; sparkles.",
    sound: "a hop, a click",
    narration: {
      en: "At the top of the rocket was a gap, just the right size. Click! It fit. It had always fit.",
      es: "En la punta del cohete había un huequito, justo del tamaño perfecto. ¡Clic! Encajó. Siempre había encajado.",
      pt: "Na ponta do foguete havia um espacinho, do tamanho certinho. Clique! Encaixou. Sempre tinha encaixado.",
    },
  },
  {
    n: 8,
    shot: "wide",
    mode: "video",
    camera: "static",
    continues: true,
    cast: ["brick", "rocket"],
    visual:
      "Wide shot of the table: the finished rocket, the little red brick smiling on top; a countdown, then the rocket lifts off in a puff of smoke.",
    motion: "Three, two, one appear in bricks; flames and smoke; the rocket rises out of the frame.",
    sound: "a countdown, a rumble, a whoosh",
    narration: {
      en: "When the children came home, the rocket was ready. Three, two, one… off it flew, little red brick and all!",
      es: "Cuando los niños volvieron a casa, el cohete estaba listo. Tres, dos, uno… ¡y despegó, con ladrillito rojo y todo!",
      pt: "Quando as crianças voltaram para casa, o foguete estava pronto. Três, dois, um… e lá se foi ele, com tijolinho vermelho e tudo!",
    },
  },
];

/** The first line in each of the app's ten languages, for the voice to read. */
export const FIRST_LINE = {
  en: SHOTS[0].narration.en,
  es: SHOTS[0].narration.es,
  pt: SHOTS[0].narration.pt,
  fr: "Sur la table de la salle de jeux, les briques construisaient une fusée, avec des hublots ronds et un nez rouge vif.",
  de: "Oben auf dem Spieltisch bauten die Steine eine Rakete, mit runden Fenstern und einer knallroten Spitze.",
  it: "Sul tavolo della stanza dei giochi, i mattoncini costruivano un razzo, con gli oblò rotondi e il muso rosso acceso.",
  ru: "На столе в детской кирпичики строили ракету — с круглыми окошками и ярко-красным носом.",
  zh: "在游戏室的桌子上，积木们正在搭一枚火箭，它有圆圆的舷窗和亮红色的尖鼻子。",
  ja: "あそびべやのテーブルの上で、ブロックたちがロケットをつくっていました。まるいまどに、ぴかぴかの赤いはなのロケットです。",
  ko: "놀이방 탁자 위에서 블록들이 로켓을 만들고 있었어요. 동그란 창문에 빨갛고 반짝이는 코가 달린 로켓이었지요.",
};

/** How long a shot stays on screen: as long as its words take to say, and a breath. */
export const seconds = (text, lang) => (words(text) / WPM[lang]) * 60 + 0.6;

/** The paragraphs: a shot that doesn't continue the one before it starts a new one. */
export const PARAGRAPHS = SHOTS.reduce((out, s) => {
  if (!s.continues || !out.length) out.push([]);
  out.at(-1).push(s);
  return out;
}, []);
