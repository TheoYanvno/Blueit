// The caption for a TikTok post: title (and part), credit to the writer, and hashtags.
export function tiktokCaption(story, video) {
  const part = video && video !== 'full.mp4' ? ` (${video.replace('part-', 'Part ').replace('.mp4', '').replace('Part 0', 'Part ')})` : '';
  const tag = story.subreddit.replace(/[^A-Za-z0-9]/g, '');
  const caption = `${story.title}${part}\nWritten by u/${story.author} on r/${story.subreddit}.\n#story #storytime #reddit #${tag}`;
  return caption.slice(0, 2200);                     // TikTok's caption limit
}
