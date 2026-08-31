(() => {
  "use strict";

  const media = document.getElementById("review-media");
  const cues = Array.from(document.querySelectorAll(".cue[data-seek]"));
  if (!media || cues.length === 0) return;

  function activateCue(target) {
    cues.forEach((cue) => cue.classList.toggle("active", cue === target));
  }

  function seekTo(seconds, targetId) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return false;
    media.currentTime = value;
    const target = targetId ? document.getElementById(targetId) :
      cues.find((cue) => Number(cue.dataset.seek) === value);
    if (target) {
      activateCue(target);
      target.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    const playAttempt = media.play();
    if (playAttempt && typeof playAttempt.catch === "function") {
      playAttempt.catch(() => {});
    }
    return true;
  }

  cues.forEach((cue) => {
    cue.addEventListener("click", () => seekTo(cue.dataset.seek, cue.id));
  });

  document.querySelectorAll(".seek-link[data-seek]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      seekTo(link.dataset.seek, link.dataset.target);
      history.replaceState(null, "", `#${link.dataset.target}`);
    });
  });

  media.addEventListener("timeupdate", () => {
    const current = cues.find((cue, index) => {
      const start = Number(cue.dataset.seek);
      const next = index + 1 < cues.length ? Number(cues[index + 1].dataset.seek) : Infinity;
      return media.currentTime >= start && media.currentTime < next;
    });
    if (current) activateCue(current);
  });

  const initial = Number(document.body.dataset.initialSeek);
  if (document.body.dataset.initialSeek !== "" && Number.isFinite(initial)) {
    media.currentTime = initial;
    const target = cues.find((cue) => Number(cue.dataset.seek) === initial);
    if (target) activateCue(target);
  }

  window.caseReviewBench = Object.freeze({ seekTo });
})();
