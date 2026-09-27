/**
 * Minimal NLP instance: compromise/two + only the verb and adjective plugins.
 *
 * LOCAL DEVIATION FROM UPSTREAM: upstream reaches the two plugins through Vite
 * `resolve.alias` entries, which do not exist outside a Vite build. Deep relative
 * paths bypass compromise's `exports` map the same way and work under plain Node.
 * Everything below this point is upstream behavior — the three-tier default export
 * would load 11 unused plugins and change `.verbs()` to chunk-based matching.
 */

// @ts-ignore — compromise/two ships its own types
import nlpTwo from 'compromise/two'
// @ts-ignore — not in compromise's exports map; reached by filesystem path
import verbsPlugin from '../../node_modules/compromise/src/3-three/verbs/plugin.js'
// @ts-ignore — not in compromise's exports map; reached by filesystem path
import adjectivesPlugin from '../../node_modules/compromise/src/3-three/adjectives/plugin.js'

const nlp = (nlpTwo as any).extend(verbsPlugin).extend(adjectivesPlugin)

export default nlp
