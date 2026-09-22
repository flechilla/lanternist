import { useEffect, useRef, useState } from "react";
import { asset } from "../api";

interface Props {
  image?: string | null; // asset id
  video?: string | null; // asset id, shown as a still frame (thumbnail)
  label?: string; // the paper label on the frame
  mark?: string; // a note painted on the right of the frame
  square?: boolean;
  empty?: string; // text on dark glass when there is no picture
  drawing?: boolean;
  alt?: string;
}

/** A painted glass lantern slide in its oak frame: every picture the app shows sits in one. */
export default function Slide({ image, video, label, mark, square, empty, drawing, alt = "" }: Props) {
  // A picture that arrives while the page is open warms in like a lamp; one already there doesn't.
  const first = useRef(image);
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    if (image && image !== first.current) setFresh(true);
  }, [image]);

  return (
    <div className={`slide${square ? " square" : ""}`}>
      <div className="aperture">
        {image ? (
          <img
            key={image}
            src={asset(image)}
            alt={alt}
            loading="lazy"
            className={fresh ? "fresh" : undefined}
          />
        ) : video ? (
          <video src={`${asset(video)}#t=2`} preload="metadata" muted playsInline aria-label={alt} />
        ) : (
          <div className={`empty${drawing ? " drawing" : ""}`}>
            {drawing ? "Drawing…" : (empty ?? "Not drawn yet")}
          </div>
        )}
      </div>
      {label && <span className="slide-label">{label}</span>}
      {mark && <span className="slide-mark">{mark}</span>}
    </div>
  );
}
