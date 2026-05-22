async function main() {
  const url =
    "https://searx.be/search?q=" +
    encodeURIComponent('site:fiverr.com car wrap "I will"') +
    "&format=json";
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  console.log("status", res.status);
  const text = await res.text();
  console.log("body start:", text.slice(0, 500));
  try {
    const j = JSON.parse(text);
    console.log("results", j.results?.length);
    j.results?.slice(0, 5).forEach((r: { url: string; title: string }) =>
      console.log(r.url, "|", r.title?.slice(0, 50))
    );
  } catch {
    console.log("not json");
  }
}

main();
