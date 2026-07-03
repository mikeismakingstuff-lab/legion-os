import fs from 'node:fs/promises';

const README_PATH = process.env.README_PATH || 'README.md';
const COMMUNITY_HEADER = '# 🌟 Community Projects';
const COMMUNITY_END_HEADER = '## 📚 Learning Resources';
const MAX_AGE_MONTHS = Number.parseInt(process.env.MAX_AGE_MONTHS || '15', 10);
const FAIL_ON_FINDINGS = (process.env.FAIL_ON_FINDINGS || 'true').toLowerCase() !== 'false';
const GITHUB_TOKEN = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || '';

function subtractMonths(date, months) {
  const next = new Date(date);
  next.setUTCMonth(next.getUTCMonth() - months);
  return next;
}

function normalizeRepo(owner, repo) {
  return {
    owner,
    repo: repo.replace(/\.git$/, ''),
  };
}

function parseGitHubRepos(markdown) {
  const regex = /\(https:\/\/github\.com\/([^\s/)]+)\/([^\s/)]+)(?:\/[^)]*)?\)/g;
  const repos = new Map();

  for (const match of markdown.matchAll(regex)) {
    const { owner, repo } = normalizeRepo(match[1], match[2]);
    const slug = `${owner}/${repo}`;

    if (!repos.has(slug)) {
      repos.set(slug, {
        owner,
        repo,
        slug,
        url: `https://github.com/${slug}`,
      });
    }
  }

  return repos;
}

function extractCommunitySection(readme) {
  const start = readme.indexOf(COMMUNITY_HEADER);
  const end = readme.indexOf(COMMUNITY_END_HEADER);

  if (start === -1 || end === -1 || end <= start) {
    throw new Error('Could not locate the Community Projects section boundaries in README.md');
  }

  return readme.slice(start, end);
}

async function fetchRepo(slug) {
  const response = await fetch(`https://api.github.com/repos/${slug}`, {
    headers: {
      Accept: 'application/vnd.github+json',
      'User-Agent': 'awesome-langgraph-repo-checks',
      ...(GITHUB_TOKEN ? { Authorization: `Bearer ${GITHUB_TOKEN}` } : {}),
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub API request failed for ${slug}: ${response.status} ${response.statusText} ${body}`);
  }

  return response.json();
}

function classifyRepo(repo, cutoffDate, isCommunityRepo) {
  const pushedAt = repo.pushed_at ? new Date(repo.pushed_at) : null;
  const archived = Boolean(repo.archived);
  const outdated = isCommunityRepo ? (pushedAt ? pushedAt < cutoffDate : true) : false;

  return {
    slug: repo.full_name,
    url: repo.html_url,
    archived,
    pushedAt,
    outdated,
    isCommunityRepo,
  };
}

function buildTable(title, rows) {
  const lines = [];
  lines.push(`## ${title}`);
  lines.push('');

  if (rows.length === 0) {
    lines.push('None found.');
    lines.push('');
    return lines;
  }

  lines.push('| Repository | Last Push | Scope | Status |');
  lines.push('|---|---|---|---|');

  for (const row of rows) {
    const lastPush = row.pushedAt ? row.pushedAt.toISOString().slice(0, 10) : 'unknown';
    const scope = row.isCommunityRepo ? 'Community Projects' : 'README';
    const status = [
      ...(row.archived ? ['archived'] : []),
      ...(row.outdated ? ['outdated'] : []),
    ].join(', ');

    lines.push(`| [${row.slug}](${row.url}) | ${lastPush} | ${scope} | ${status} |`);
  }

  lines.push('');
  return lines;
}

function buildSummary({ totalReposChecked, archivedFindings, outdatedFindings, cutoffDate }) {
  const lines = [];
  lines.push('# Repo Checks');
  lines.push('');
  lines.push(`- GitHub repos checked: ${totalReposChecked}`);
  lines.push(`- Archived findings: ${archivedFindings.length}`);
  lines.push(`- Outdated community project findings: ${outdatedFindings.length}`);
  lines.push(`- Community staleness cutoff: ${cutoffDate.toISOString().slice(0, 10)} (${MAX_AGE_MONTHS} months)`);
  lines.push('');
  lines.push(...buildTable('Archived Repositories', archivedFindings));
  lines.push(...buildTable('Outdated Community Projects', outdatedFindings));
  return lines.join('\n');
}

async function writeGitHubSummary(markdown) {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY;
  if (!summaryPath) return;
  await fs.appendFile(summaryPath, `${markdown}\n`, 'utf8');
}

async function main() {
  const readme = await fs.readFile(README_PATH, 'utf8');
  const communitySection = extractCommunitySection(readme);
  const allRepos = parseGitHubRepos(readme);
  const communityRepos = parseGitHubRepos(communitySection);
  const cutoffDate = subtractMonths(new Date(), MAX_AGE_MONTHS);

  if (!GITHUB_TOKEN) {
    console.warn('Warning: GITHUB_TOKEN is not set. GitHub API rate limits may be too low for this check.');
  }

  const archivedFindings = [];
  const outdatedFindings = [];

  for (const repo of allRepos.values()) {
    const data = await fetchRepo(repo.slug);
    const finding = classifyRepo(data, cutoffDate, communityRepos.has(repo.slug));

    if (finding.archived) {
      archivedFindings.push(finding);
    }

    if (finding.outdated) {
      outdatedFindings.push(finding);
    }
  }

  archivedFindings.sort((a, b) => a.slug.localeCompare(b.slug));
  outdatedFindings.sort((a, b) => a.slug.localeCompare(b.slug));

  const summary = buildSummary({
    totalReposChecked: allRepos.size,
    archivedFindings,
    outdatedFindings,
    cutoffDate,
  });

  console.log(summary);
  await writeGitHubSummary(summary);

  if ((archivedFindings.length > 0 || outdatedFindings.length > 0) && FAIL_ON_FINDINGS) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
