import { asset, CAMERA_NAMES, fmtUsd, thumb, type CastMember, type Step, type Storyboard } from "../api";
import { sceneWords, type SceneState } from "../reel";
import { Wave } from "./ReelSlide";

// How long a step took and what it cost: "in 16.2 s · $0.08".
function took(step: Step | undefined): string {
  const parts = [
    step?.secs != null && `in ${step.secs.toFixed(1)} s`,
    step?.cost_usd && fmtUsd(step.cost_usd),
  ];
  return parts.filter(Boolean).join(" · ");
}

function joinAnd(items: string[]): string {
  return items.length < 2
    ? (items[0] ?? "")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

const capital = (s: string) => s[0].toUpperCase() + s.slice(1);

interface SceneProps {
  sb: Storyboard;
  s: SceneState;
  seconds: number;
  playing: boolean;
  onListen: () => void;
}

/** A scene on the reel, looked at closely: its picture or clip, its line, and how far each of its
 * steps has got, with the time and money each took. */
export function SceneCard({ sb, s, seconds, playing, onListen }: SceneProps) {
  const sc = sb.scenes.find((x) => x.n === s.n)!;
  const st = s.steps;
  const place = sb.places.find((p) => p.id === sc.place)?.name;
  const who = sb.cast.filter((c) => sc.cast.includes(c.id)).map((c) => c.name);

  const media =
    s.video && s.motion === "done" ? (
      <video
        key={s.video}
        src={asset(s.video)}
        poster={thumb(s.image, 768)}
        muted
        loop
        playsInline
        autoPlay
      />
    ) : s.image ? (
      <img src={thumb(s.image, 768)} alt="" />
    ) : s.voice === "done" ? (
      <Wave n={s.n} seconds={seconds} />
    ) : (
      <div className="empty">{s.voice === "working" ? "Recording the narration…" : "Nothing made yet"}</div>
    );

  const voice =
    s.voice === "done"
      ? `${seconds.toFixed(1)} s of narration`
      : s.voice === "working"
        ? "being recorded now"
        : "waiting its turn";
  const picture =
    s.again !== null
      ? "to be drawn again"
      : s.picture === "working" || s.picture === "waiting"
        ? s.image
          ? "being drawn again now"
          : "being painted now"
        : s.picture === "done"
          ? (st.keyframes?.tries ?? 0) > 1
            ? "drawn again after the check"
            : "drawn"
          : "not drawn yet";
  const check =
    s.failing !== null ? (
      <span className="bad">still fails: {s.failing}</span>
    ) : s.again !== null ? (
      <span className="bad">{s.again}</span>
    ) : st.check?.state === "done" || st.check?.state === "cached" ? (
      <span className="ok">passed</span>
    ) : st.check?.state === "working" ? (
      "being checked now"
    ) : (
      "not yet"
    );
  const motion =
    s.motion === "still"
      ? `a still, camera: ${CAMERA_NAMES[sc.camera].toLowerCase()}`
      : s.motion === "done"
        ? "animated"
        : s.motion === "working"
          ? "being animated now"
          : s.motion === "waiting"
            ? `in the queue${s.ahead ? `, ${s.ahead} ahead` : ""}`
            : "after the pictures";

  return (
    <>
      <div className="media">
        {media}
        <span className="state-chip">{capital(sceneWords(s))}</span>
        <span className="num">No. {s.n}</span>
      </div>
      <div className="body">
        <p className="line">{sc.narration.map((l) => l.text).join(" ")}</p>
        <dl>
          <dt>Voice</dt>
          <dd>
            {voice} <small>{took(st.narration)}</small>
          </dd>
          <dt>Picture</dt>
          <dd>
            {picture} <small>{took(st.keyframes)}</small>
          </dd>
          {st.check && (
            <>
              <dt>Check</dt>
              <dd>{check}</dd>
            </>
          )}
          <dt>Motion</dt>
          <dd>
            {motion} <small>{took(st.motion)}</small>
          </dd>
          <dt>Cut</dt>
          <dd>{s.cut === "done" ? "in the film" : "not yet"}</dd>
        </dl>
        {(who.length > 0 || place) && (
          <p className="meta">{[joinAnd(who), place].filter(Boolean).join(" · ")}</p>
        )}
        {s.audio && (
          <div className="acts">
            <button className="hbtn" onClick={onListen} aria-pressed={playing}>
              {playing ? "Stop" : "Listen"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}

interface CastProps {
  member: CastMember | null; // null: the cast sheet
  step: Step | undefined;
  image: string | null;
  drawing: boolean;
  scenes: number; // the scenes the character is in
  total: number;
}

/** A portrait on the reel, or the cast sheet, looked at closely. */
export function CastCard({ member, step, image, drawing, scenes, total }: CastProps) {
  return (
    <>
      <div className="media tall">
        {image ? (
          <img src={thumb(image, 768)} alt="" />
        ) : (
          <div className="empty">{drawing ? "Being drawn…" : "Not drawn yet"}</div>
        )}
        <span className="state-chip">{image ? "Drawn" : drawing ? "Being drawn" : "Planned"}</span>
      </div>
      <div className="body">
        <p className="line">
          {member
            ? member.look
            : "Everyone together, so every portrait and picture is drawn from the same faces."}
        </p>
        <dl>
          <dt>Where</dt>
          <dd>{member ? `in ${scenes} of ${total} scenes` : "every portrait is drawn from it"}</dd>
          {step?.secs != null && (
            <>
              <dt>Picture</dt>
              <dd>drawn {took(step)}</dd>
            </>
          )}
        </dl>
      </div>
    </>
  );
}
