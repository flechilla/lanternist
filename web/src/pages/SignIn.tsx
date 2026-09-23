import { useSearchParams } from "react-router-dom";

/** The hosted edition's front door. AuthKit's own pages do the signing in, and come back here with why
 * when it didn't work. */
export default function SignIn() {
  const [params] = useSearchParams();
  const error = params.get("error");
  return (
    <section className="panel stack sign-in" aria-labelledby="sign-in-title">
      <h1 id="sign-in-title">Sign in to Lanternist</h1>
      <p>
        Your stories and films are kept in your account. Sign in with a code sent to your email, or with
        Google. There's no password.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="actions">
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
