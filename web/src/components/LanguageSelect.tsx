import { useOptions } from "../hooks";

/** The languages a story can be written and narrated in, as the backend lists them. */
export default function LanguageSelect({
  id,
  value,
  onChange,
}: {
  id?: string;
  value: string;
  onChange: (language: string) => void;
}) {
  const opts = useOptions();
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {(opts?.languages ?? [{ id: "en", name: "English" }]).map((l) => (
        <option key={l.id} value={l.id}>
          {l.name}
        </option>
      ))}
    </select>
  );
}
