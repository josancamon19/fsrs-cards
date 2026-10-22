# Suspended cards — rewrite queue (39)

_Exported 2026-10-22 12:42 from https://fsrs-cards-8378.fly.dev_

## Math4ML::Probability & Information Theory::00 Map · Big Picture

- **Many things are “just an expectation” \(\mathbb{E}[f(X)]\). Name 6 and their \(f\).**
  - Answer: • mean: \(f(x)=x\) • second moment: \(f(x)=x^2\) • variance: \(f(x)=(x-\mu)^2\) • MSE / ML loss: \(f=(\hat y-y)^2\) or any error \(\ell\) • entropy: \(f(x)=-\log p(x)\) • cross-entropy: \(f(x)=-\log q(x)\), averaged under \(p\) • covariance: \(f=(x-\mu_X)(y-\mu_Y)\)
  - Reason: List / too many items → split into single-answer cards · suspended 2026-10-22 · 2 reviews, 0 Again, D 4.8
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439633, note 1792626439632
- **Which four quantities all measure spread / uncertainty, and of what?**
  - Answer: • Variance / std: spread of numbers around their mean • MSE: spread of predictions around the targets • Surprise: how unexpected one outcome is • Entropy: average surprise, i.e. uncertainty of a whole distribution
  - Reason: List / too many items → split into single-answer cards · suspended 2026-10-22 · 2 reviews, 0 Again, D 2.1
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439635, note 1792626439634
- **Where does squaring show up, why, and how do we undo it?**
  - Answer: Variance, MSE, L2 norm, RMS. Squaring makes every deviation positive (so they can't cancel) and punishes big deviations more. Taking the square root (std, RMS, ‖x‖) brings you back to the original units.
  - Reason: — · suspended 2026-10-22 · 1 reviews, 0 Again, D 2.1
  - Source: [Math › 3.2. Scale normalization](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=3.2.%20Scale%20normalization)
  - ids: card 1792626439639, note 1792626439638
- **Knowledge tree: name the 8 branches of probability-for-ML covered in this deck.**
  - Answer: • Interpretations: frequentist vs Bayesian • Distributions: PMF, PDF, uniform • Rules: joint, conditional, marginal, chain, Bayes, independence • Summaries: expectation, variance, std, mode, median • Relationships: covariance, correlation, causation, sparsity • Normalization: softmax, L2, LayerNorm, RMSNorm • Information theory: surprise → entropy → cross-entropy → KL, perplexity • Learning: loss 
  - Reason: — · suspended before tracking · 0 reviews, 0 Again
  - Source: [Math › Probability](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=Probability)
  - ids: card 1792626439629, note 1792626439628
- **Name the four things that turn out to be the same optimisation goal when training a classifier.**
  - Answer: Minimise cross-entropy loss = minimise NLL = maximise likelihood (MLE) = minimise KL(p‖q) (since \(H(p)\) is fixed by the data).
  - Reason: — · suspended before tracking · 1 reviews, 0 Again, D 5.1
  - Source: [Math › 5.3 Cross-Entropy Loss == Negative Log Likelihood](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.3%20Cross-Entropy%20Loss%20%3D%3D%20Negative%20Log%20Likelihood)
  - ids: card 1792626439637, note 1792626439636

## Math4ML::Probability & Information Theory::01 Foundations · Interpretations & Vocabulary

- **Do frequentists and Bayesians use different maths?**
  - Answer: No. They use the same rules (sum, product, Bayes). They differ in what probability means and which things you may assign it to (for example one-off events and parameters).
  - Reason: Vocabulary/philosophy trivia, not useful for intuition · suspended 2026-10-22 · 1 reviews, 0 Again, D 2.1
  - Source: [Math › 1. Etymology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=1.%20Etymology)
  - ids: card 1792626439647, note 1792626439646
- **Possible vs probable?**
  - Answer: Possible: P > 0 (it can happen). Probable / likely: more likely than not (informally > 50%).
  - Reason: Vocabulary/philosophy trivia, not useful for intuition · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 1. Etymology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=1.%20Etymology)
  - ids: card 1792626439659, note 1792626439658
- **Does “chance” mean “very likely”?**
  - Answer: No. It's a neutral synonym for probability (“a 10% chance”).
  - Reason: Vocabulary/philosophy trivia, not useful for intuition · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 1. Etymology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=1.%20Etymology)
  - ids: card 1792626439661, note 1792626439660
- **What was the probability of rain in Paris on 1 March 1850? How do the two schools answer?**
  - Answer: Frequentist: it's a fixed one-off fact (0 or 1), not repeatable, so there's no meaningful probability. Bayesian: you don't know, so assign a belief, e.g. the base rate of rainy March days (~40%).
  - Reason: — · suspended 2026-10-22 · 1 reviews, 1 Again, D 6.4
  - Source: [Math › 1. Etymology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=1.%20Etymology)
  - ids: card 1792626439651, note 1792626439650
- **Why is “1 in 20 startups succeed” an ambiguous frequentist answer for one particular startup?**
  - Answer: Reference-class problem: 1 in 20 out of which startups? All of them, AI startups, ones with repeat founders? Each group gives a different frequency.
  - Reason: — · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 1. Etymology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=1.%20Etymology)
  - ids: card 1792626439653, note 1792626439652
- **What are probability theory and information theory each for?**
  - Answer: Probability: making statements and reasoning under uncertainty. Information theory: quantifying how much uncertainty a distribution contains.
  - Reason: — · suspended 2026-10-22 · 2 reviews, 1 Again, D 7.6
  - Source: [Math › Probability](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=Probability)
  - ids: card 1792626439641, note 1792626439640

## Math4ML::Probability & Information Theory::02 Distributions & Rules

- **What is a PDF? Give its constraints.**
  - Answer: Probability density function, for continuous variables: \(p(x) \ge 0\) and \(\int p(x)\,dx = 1\). Probabilities are areas over ranges: \(P(a\le X\le b)=\int_a^b p(x)\,dx\).
  - Reason: Vocabulary/philosophy trivia, not useful for intuition · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.1 Distributions](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.1%20Distributions)
  - ids: card 1792626439667, note 1792626439666
- **Why must it be \(P(x) > 0\), not \(\ge 0\), in \(P(y\mid x) = P(x,y)/P(x)\)?**
  - Answer: You can't divide by zero. Conditioning on an impossible event is undefined.
  - Reason: Vague or pedantic 'why' → replace with a concrete step or exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439686, note 1792626439685
- **Marginal (sum rule): \( P(x) = \sum_y P(x, y) \) (continuous: \( p(x) = \int p(x, y)\,dy \))**
  - Answer: Marginalising = ignore a variable by summing over all its values.
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439688, note 1792626439687
- **Marginal (sum rule): \( P(x) = \sum_y P(x, y) \) (continuous: \( p(x) = \int p(x, y)\,dy \))**
  - Answer: Marginalising = ignore a variable by summing over all its values.
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439689, note 1792626439687
- **What is a PMF? Give its two constraints.**
  - Answer: Probability mass function, for discrete variables: a probability for each outcome. \(0 \le P(x) \le 1\) and \(\sum_x P(x) = 1\).
  - Reason: — · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.1 Distributions](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.1%20Distributions)
  - ids: card 1792626439665, note 1792626439664

## Math4ML::Probability & Information Theory::04 Expectation · Variance · Std

- **Variance: \( \mathrm{Var}(X) = \mathbb{E}[(X-\mu)^2] \) = \( \mathbb{E}[X^2] - \mathbb{E}[X]^2 \)**
  - Answer: Definition = average squared distance from the mean; the second form is an algebraic shortcut.
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439753, note 1792626439752
- **Variance: \( \mathrm{Var}(X) = \mathbb{E}[(X-\mu)^2] \) = \( \mathbb{E}[X^2] - \mathbb{E}[X]^2 \)**
  - Answer: Definition = average squared distance from the mean; the second form is an algebraic shortcut.
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439754, note 1792626439752
- **A die's expected value is 3.5, yet you can never roll 3.5. Why is that fine?**
  - Answer: E[X] is where the long-run average settles, not a single outcome, like “2.4 children per family”.
  - Reason: this is definitely not a good question · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439739, note 1792626439738
- **Why is \(\mathbb{E}[X] = \sum_x P(x)\,x\) “the mean”?**
  - Answer: A sample average is \(\sum \text{value} \times \frac{\text{count}}{N}\). As N grows, count/N → P(x), so the average → \(\sum P(x)\,x\). E[X] is the mean, defined for a distribution instead of a list.
  - Reason: the answer is rly shitty and unintuitive · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439737, note 1792626439736
- **Expectation of a function: \( \mathbb{E}[f(X)] = \sum_x P(x)\,f(x) \) (continuous: \( \int p(x)\,f(x)\,dx \))**
  - Answer: A probability-weighted average. With \(f(x)=x\) it's the mean μ.
  - Reason: same for this one, though I need to check PDFs better · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439735, note 1792626439733
- **Expectation of a function: \( \mathbb{E}[f(X)] = \sum_x P(x)\,f(x) \) (continuous: \( \int p(x)\,f(x)\,dx \))**
  - Answer: A probability-weighted average. With \(f(x)=x\) it's the mean μ.
  - Reason: should add the word discrete? this one is bad overall · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439734, note 1792626439733

## Math4ML::Probability & Information Theory::06 Normalization · Softmax, LayerNorm, RMSNorm, L2

- **What does LayerNorm make the network focus on?**
  - Answer: The token's pattern (which features stand out relative to the rest), not its overall loudness.
  - Reason: Vague or pedantic 'why' → replace with a concrete step or exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 3.2. Scale normalization](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=3.2.%20Scale%20normalization)
  - ids: card 1792626439832, note 1792626439831

## Math4ML::Probability & Information Theory::07 Covariance · Correlation · Causation · Sparsity

- **Covariance: \( \mathrm{Cov}(X,Y) = \mathbb{E}[(X-\mu_X)(Y-\mu_Y)] \)**
  - Answer: Average product of deviations, weighted by the joint P(x, y).
  - Reason: Formula fill-in with no question (bare name) → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 4. More Definitions](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=4.%20More%20Definitions)
  - ids: card 1792626439852, note 1792626439851

## Math4ML::Probability & Information Theory::08 Loss Functions · MSE

- **Expected loss: \( \mathbb{E}_{(x,y)\sim \mathcal{D} }\left[\ell(f(x), y)\right] \)**
  - Answer: Loss is just an expectation: the average error over the data, under the model's current weights.
  - Reason: Formula fill-in with no question (bare name) → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 2.2 Terminology](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=2.2%20Terminology)
  - ids: card 1792626439883, note 1792626439882

## Math4ML::Probability & Information Theory::09 Information Theory · Surprise, Entropy, CE, KL, Perplexity

- **Three behaviours that make surprise a good classification loss.**
  - Answer: • Wrong + confident → huge penalty • Unsure → moderate penalty • Right + confident → ≈ 0 loss
  - Reason: List / too many items → split into single-answer cards · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439967, note 1792626439966
- **Entropy: \( H(p) = -\sum_x p(x)\log p(x) \) = expected surprise**
  - Answer: 
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439927, note 1792626439926
- **Entropy: \( H(p) = -\sum_x p(x)\log p(x) \) = expected surprise**
  - Answer: 
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439928, note 1792626439926
- **Cross-entropy: \( H(p, q) = -\sum_x p(x)\log q(x) \)**
  - Answer: Weights from reality p, surprises from the model q.
  - Reason: Formula fill-in with no question (bare name) → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439938, note 1792626439937
- **KL divergence: \( D_{KL}(p \Vert q) = H(p, q) - H(p) \) = \( \sum_x p(x)\log\frac{p(x)}{q(x)} \)**
  - Answer: 
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439948, note 1792626439947
- **KL divergence: \( D_{KL}(p \Vert q) = H(p, q) - H(p) \) = \( \sum_x p(x)\log\frac{p(x)}{q(x)} \)**
  - Answer: 
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439949, note 1792626439947
- **Why the minus sign in \(-\log p\)?**
  - Answer: For p < 1, \(\log p\) is negative. The minus flips it positive, which gives a surprise / loss you can push down.
  - Reason: I don't rly know if this is correct, and don't understand it, is not triggering a connection or smth · suspended 2026-10-22 · 1 reviews, 1 Again, D 6.4
  - Source: [Math › 5.2 Logs and bits](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.2%20Logs%20and%20bits)
  - ids: card 1792626439905, note 1792626439904
- **Three properties surprise should have, and that \(-\log p\) satisfies.**
  - Answer: • Certain event (p = 1) → 0 surprise • Rarer → more surprising • Independent events → surprises add
  - Reason: question is wrong, wtf, surprise has 3 properties maybe is the question · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439901, note 1792626439900
- **Surprise (self-information): \( I(x) = -\log p(x) = \log\frac{1}{p(x)} \)**
  - Answer: 
  - Reason: the prompt doesn't make any fucking sense, like I have no idea what's asking · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.1 Expectation → Surprise → Entropy → Cross-Entropy → KL divergence](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.1%20Expectation%20%E2%86%92%20Surprise%20%E2%86%92%20Entropy%20%E2%86%92%20Cross-Entropy%20%E2%86%92%20KL%20divergence)
  - ids: card 1792626439899, note 1792626439898

## Math4ML::Probability & Information Theory::10 Likelihood & MLE

- **Why write the likelihood as \(P(x\mid\theta)\) or \(P(x;\theta)\), not \(P(x,\theta)\)?**
  - Answer: θ is a parameter you condition on, not a second random variable you observe jointly.
  - Reason: Vague or pedantic 'why' → replace with a concrete step or exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.3 Cross-Entropy Loss == Negative Log Likelihood](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.3%20Cross-Entropy%20Loss%20%3D%3D%20Negative%20Log%20Likelihood)
  - ids: card 1792626439984, note 1792626439983
- **Maximum likelihood estimation: \( \theta^* = \arg\max_\theta \log L(\theta) \)**
  - Answer: Pick the θ that makes the observed data least surprising.
  - Reason: Formula fill-in with no question (bare name) → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.3 Cross-Entropy Loss == Negative Log Likelihood](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.3%20Cross-Entropy%20Loss%20%3D%3D%20Negative%20Log%20Likelihood)
  - ids: card 1792626440001, note 1792626440000
- **Likelihood of i.i.d. data: \( L(\theta) = \prod_i P(x_i \mid \theta) \); log-likelihood: \( \log L(\theta) = \sum_i \log P(x_i \mid \theta) \)**
  - Answer: The log turns the product into a sum, which is easy to differentiate and doesn't underflow.
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.3 Cross-Entropy Loss == Negative Log Likelihood](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.3%20Cross-Entropy%20Loss%20%3D%3D%20Negative%20Log%20Likelihood)
  - ids: card 1792626439998, note 1792626439997
- **Likelihood of i.i.d. data: \( L(\theta) = \prod_i P(x_i \mid \theta) \); log-likelihood: \( \log L(\theta) = \sum_i \log P(x_i \mid \theta) \)**
  - Answer: The log turns the product into a sum, which is easy to differentiate and doesn't underflow.
  - Reason: Formula fill-in: visible half gives away the hidden half → replace with a simple exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › 5.3 Cross-Entropy Loss == Negative Log Likelihood](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=5.3%20Cross-Entropy%20Loss%20%3D%3D%20Negative%20Log%20Likelihood)
  - ids: card 1792626439999, note 1792626439997

## Math4ML::Probability & Information Theory::11 Algebra · Powers & Logs

- **Why is \(\log_2(1/2) = -1\)?**
  - Answer: Because \(2^{-1} = 1/2\). Any probability below 1 needs a negative power, so its log is negative.
  - Reason: Vague or pedantic 'why' → replace with a concrete step or exercise · suspended 2026-10-22 · 0 reviews, 0 Again
  - Source: [Math › Algebraic Relationships](bear://x-callback-url/open-note?id=BE5759A7-C98C-40E8-A3FC-A2E20506195A&header=Algebraic%20Relationships)
  - ids: card 1792626440041, note 1792626440040
