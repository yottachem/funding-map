// Reads {data, profile, start} on stdin; prints the browser picker's roadmap as JSON. Used by tests/test_site.py.
const picker = require("../site/static/picker.js");
let raw = "";
process.stdin.on("data", c => (raw += c)).on("end", () => {
  const { data, profile, start } = JSON.parse(raw);
  process.stdout.write(JSON.stringify(picker.pick(data, profile, start)));
});
