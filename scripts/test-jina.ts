async function main() {
  const target =
    "https://r.jina.ai/https://www.google.com/search?q=" +
    encodeURIComponent("site:fiverr.com car wrap");
  const res = await fetch(target);
  const t = await res.text();
  console.log(t);
}

main();
