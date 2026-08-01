import "./globals.css";

export const metadata = {
  title: "When did your dentist last say? — NHS dental access in England",
  description:
    "Search NHS dental practices in England and see what each one reported about taking new patients, and when it last said so.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en-GB">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <header className="masthead">
          <div className="wrap">
            <p className="eyebrow">Independent · Open data</p>
            <p className="wordmark">When did your dentist last say?</p>
          </div>
        </header>
        <main id="main">{children}</main>
        <footer className="footer">
          <div className="wrap">
            <p className="disclaimer">
              <strong>Not affiliated with, endorsed by, or connected to the NHS.</strong>{" "}
              Everything here is what a practice told the NHS on the date shown. It is not a
              statement of what is true today — practices are meant to update at least every
              90 days, and many do not.
            </p>
            <p className="attribution">
              Information from the NHS website. Information from the NHS website is licensed
              under the Open Government Licence v3.0. Contains ONS data licensed under the
              Open Government Licence v3.0. Postcode lookup by postcodes.io.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
