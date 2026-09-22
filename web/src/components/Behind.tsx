import { Fragment } from "react";
import { fmtSeconds, fmtUsd, type Job, type Step } from "../api";
import { stageCount, stageShare, type SceneState } from "../reel";
import { Log } from "./JobProgress";

// A cell of the grid: where one scene's step in one stage has got to.
function cell(step: Step | undefined, s: SceneState, stage: string): string | undefined {
  if (stage === "check" && s.failing !== null) return "flag";
  if (step?.state === "failed" || (stage === "keyframes" && s.again !== null)) return "bad";
  if (step?.state === "working" || step?.state === "waiting") return step.state;
  if (step?.state === "done" || step?.state === "cached") return "done";
  return undefined;
}

interface Props {
  job: Job;
  scenes: SceneState[];
  onScene: (n: number) => void;
}

/** A job's workings, for whoever wants them: each stage with its model, time and spend; every scene's
 * step in every stage; and the log. */
export default function Behind({ job, scenes, onScene }: Props) {
  const stages = Object.entries(job.progress?.stages ?? {});
  const perScene = stages.filter(([key]) => scenes.some((s) => s.steps[key]));
  return (
    <div className="behind">
      <div>
        <h3>Stages, models and spend</h3>
        <div className="srows">
          <div className="srow head">
            <span>Stage</span>
            <span className="hb" />
            <span>Items</span>
            <span className="tmh">Time</span>
            <span>Spent</span>
          </div>
          {stages.map(([key, st]) => (
            <div key={key} className={`srow ${st.status}`}>
              <div className="nm">
                <b>{st.label ?? key}</b>
                {st.model && <span>{st.local ? `${st.model} · this machine` : st.model}</span>}
              </div>
              <div className="bar">
                <i style={{ width: `${stageShare(st) * 100}%` }} />
              </div>
              <span className="n">{stageCount(st)}</span>
              <span className="tm">{st.secs ? fmtSeconds(st.secs) : ""}</span>
              <span className="usd">{st.spent_usd ? fmtUsd(st.spent_usd) : st.local ? "free" : ""}</span>
            </div>
          ))}
        </div>
      </div>
      {perScene.length > 0 && (
        <div>
          <h3>Every scene, every step</h3>
          <div className="matrix">
            <div className="mgrid" style={{ gridTemplateColumns: `76px repeat(${scenes.length}, 13px)` }}>
              <span />
              {scenes.map((s) => (
                <span key={s.n} className="hn">
                  {s.n === 1 || s.n % 5 === 0 ? s.n : ""}
                </span>
              ))}
              {perScene.map(([key, st]) => (
                <Fragment key={key}>
                  <span className="rl">{st.label ?? key}</span>
                  {scenes.map((s) => (
                    <button
                      key={s.n}
                      type="button"
                      className="cell"
                      tabIndex={-1}
                      data-s={cell(s.steps[key], s, key)}
                      aria-label={`Scene ${s.n}, ${st.label ?? key}`}
                      onClick={() => onScene(s.n)}
                    />
                  ))}
                </Fragment>
              ))}
            </div>
          </div>
          <div className="legend" aria-hidden="true">
            <span>
              <i className="cell" />
              not yet
            </span>
            <span>
              <i className="cell" data-s="waiting" />
              in a queue
            </span>
            <span>
              <i className="cell" data-s="working" />
              being made
            </span>
            <span>
              <i className="cell" data-s="done" />
              done
            </span>
            <span>
              <i className="cell" data-s="bad" />
              to draw again
            </span>
            <span>
              <i className="cell" data-s="flag" />
              still fails the check
            </span>
          </div>
        </div>
      )}
      <div>
        <h3>Log</h3>
        <Log job={job} />
      </div>
    </div>
  );
}
