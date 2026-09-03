---
folder: Tools & AI
topics: [ai-tools]
source: https://www.instagram.com/reel/DaIeQ59tAfu/
date: 2026-06-28
type: reel-note
content_type: tutorial
kind: video
categories: [Tools & AI, Content & Creator]
status: inbox
review_question: Why does simulating goals with a Poisson draw tell you more than simply naming the likely winner?
---

# ML Model to Predict World Cup

**Main idea:** Build a football match predictor using Elo-style team ratings and Poisson-based goal simulation on 50,000 historical international games.
**Useful for:** Anyone wanting to build a data-driven sports prediction model from historical match data.

## Key points
- A single match prediction is unreliable — simulating 10,000 times gives a stable win probability.
- Weighting recent matches and more important tournaments makes the rating more accurate than raw win/loss counts.
- The model outputs both a win-probability and a most-likely scoreline from the Poisson distribution.

## Steps
1. Source a GitHub dataset of ~50,000 international matches since 1872 (teams, score, date, match type).
2. Build an Elo-style strength rating for every team: winner gains points, loser drops, weighted by recency and tournament importance.
3. Feed both teams' ratings into a Poisson model to compute expected goals and derive win odds and the most likely score.
4. Simulate the match 10,000 times and use the win-count percentage as the final prediction.

## Recommended
- [ ] ✅ [Elo Rating System](https://en.wikipedia.org/wiki/Elo_rating_system)
- [ ] ✅ [Poisson Distribution](https://en.wikipedia.org/wiki/Poisson_distribution)

**Why save:** Compact, end-to-end walkthrough of combining Elo ratings and Poisson simulation into a real sports prediction tool.

**Original:** https://www.instagram.com/reel/DaIeQ59tAfu/
#machine-learning #football #prediction

## Transcript

My friends convinced me to join their prediction pool for the World Cup, so let's build a machine learning model to try to beat them. For this project, I will use a dataset on GitHub that has almost every international match ever played. That comes out to about 50,000 international games since 1872. For each game, we get the two teams, the final score, when it was played and what kind of game it was. Using all of that data, I can build a strength index for every team. Basically, after each game, the winner gains rating and the loser drops, with recent matches and more important tournaments counting more points. This way, every team ends up with a single number of how strong they actually are right now. It's kind of like a chess elo bit for football. To predict the game, I take the two teams' ratings and turn that into the expected goals for both sides using a Poisson model. That gives me the odds of a team winning and the most likely score. But because one match could be mostly luck, a single prediction is meaningless. So I simulate the game 10,000 times and count how often each team wins. And that final percentage is the real prediction. So let's try it out on the upcoming game of Brazil vs Japan. As we see, Brazil definitely has the higher odds and the model suggests that the 1-0 is the most likely score. So I'm very excited to see how that game works out. If you want the full code to play around with it, comment World Cup and I'll send it over to you. I'll send it over. Thank you.
