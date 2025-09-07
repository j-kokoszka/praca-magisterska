const { execSync } = require('child_process');
const args = require('minimist')(process.argv.slice(2));

// Parametry
const scenario = args.scenario;         // np. constant_load
const host = args.host || 'http://localhost:8000';
const vus = args.vus || 5;
const duration = args.duration || '30s';

if (!scenario) {
    console.log("Usage: node runner.js --scenario <name> [--host <url>] [--vus <number>] [--duration <time>]");
    process.exit(1);
}

const scenarioPath = `./scenarios/${scenario}.js`;

try {
    console.log(`Running scenario: ${scenario}`);
    console.log(`Host: ${host}, VUs: ${vus}, Duration: ${duration}`);
    
    // Ustawienie zmiennych środowiskowych dla scenariusza k6
    const env = `BASE_URL=${host} VUS=${vus} DURATION=${duration}`;
    execSync(`${env} k6 run ${scenarioPath}`, { stdio: 'inherit' });

} catch (err) {
    console.error("Error running scenario:", err.message);
}

