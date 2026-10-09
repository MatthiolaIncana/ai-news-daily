export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(triggerGitHub(env, controller.scheduledTime));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/health") {
      return new Response("Not found", { status: 404 });
    }
    return Response.json({
      ok: true,
      service: "ai-news-daily-watchdog",
      repo: env.GITHUB_REPO || "MatthiolaIncana/ai-news-daily",
    });
  },
};

async function triggerGitHub(env, scheduledTime) {
  const repo = env.GITHUB_REPO || "MatthiolaIncana/ai-news-daily";
  const workflow = env.GITHUB_WORKFLOW || "daily-news.yml";
  const ref = env.GITHUB_REF || "main";

  if (!env.GITHUB_TOKEN) {
    throw new Error("Missing Worker secret: GITHUB_TOKEN");
  }

  const endpoint =
    `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ai-news-daily-cloudflare-watchdog/1.0",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref,
      inputs: {
        retry_mode: "true",
        trigger_source: "cloudflare-watchdog",
        scheduled_time: new Date(scheduledTime).toISOString(),
      },
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `GitHub workflow dispatch failed: ${response.status} ${body}`,
    );
  }
}
