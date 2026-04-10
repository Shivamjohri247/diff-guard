// TypeScript server that imports config
import { defaultConfig, Config } from './config';

function start(config: Config) {
    console.log(`Starting on ${config.host}:${config.port}`);
}
