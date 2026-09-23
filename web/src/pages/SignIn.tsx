import { useSearchParams } from "react-router-dom";

/** Why a sign-in didn't work, by the code the server sends back (`auth.Failure`). The page says it in
 * its own words, so a link can't put text of its own on the front door. */
const FAILURES: Record<string, string> = {
  expired: "That sign-in link has expired or was opened in another browser. Sign in again.",
  cancelled: "The sign-in didn't finish. Sign in again.",
  refused: "The sign-in was refused. Sign in again.",
  unavailable: "Signing in isn't working right now. Try again in a few minutes.",
};

/** The hosted edition's front door. AuthKit's own pages do the signing in, and come back here with why
 * when it didn't work. */
export default function SignIn() {
  const [params] = useSearchParams();
  const code = params.get("error");
  const error = code && (FAILURES[code] ?? "The sign-in didn't work. Sign in again.");
  return (
    <section className="panel stack sign-in" aria-labelledby="sign-in-title">
      <h1 id="sign-in-title">Sign in to Lanternist</h1>
      <p>
        Your stories and films are kept in your account. Sign in with a code sent to your email, or with
        Google. There's no password.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <a className="btn primary" href="/api/auth/sign-in">
          Sign in
        </a>
        <a className="btn" href="/api/auth/sign-in?screen=sign-up">
          Create an account
        </a>
      </div>
    </section>
  );
}
