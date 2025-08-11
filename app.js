class NextTrainApp {
    constructor() {
        this.data = null;
        this.userLocation = null;
        this.nearestStation = null;
        this.selectedLine = null;
        this.selectedDirection = null;
        this.countdownInterval = null;

        this.loadingEl = document.getElementById('loading');
        this.errorEl = document.getElementById('error');
        this.appEl = document.getElementById('app');
        this.stationNameEl = document.getElementById('stationName');
        this.distanceEl = document.getElementById('distance');
        this.lineSelectorEl = document.getElementById('lineSelector');
        this.directionSelectorEl = document.getElementById('directionSelector');
        this.trainTimeEl = document.getElementById('trainTime');
        this.countdownEl = document.getElementById('countdown');
        this.trainInfoEl = document.getElementById('trainInfo');

        this.init();
    }

    async init() {
        try {
            await this.loadData();
            try {
                await this.getUserLocation();
            } catch (locationError) {
                this.showLocationFallback();
                return;
            }
            this.findNearestStation();
            this.setupUI();
            this.startCountdown();
        } catch (error) {
            this.showError(error.message);
        }
    }

    async loadData() {
        try {
            const response = await fetch('data.json');
            if (!response.ok) {
                throw new Error('无法加载数据');
            }
            this.data = await response.json();
        } catch (error) {
            throw new Error('加载数据失败');
        }
    }

    async getUserLocation() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error('您的设备不支持定位功能'));
                return;
            }

            navigator.geolocation.getCurrentPosition(
                (position) => {
                    this.userLocation = {
                        lat: position.coords.latitude,
                        lng: position.coords.longitude
                    };
                    resolve();
                },
                (error) => {
                    let message = '定位失败';
                    switch (error.code) {
                        case error.PERMISSION_DENIED:
                            message = '定位权限被拒绝';
                            break;
                        case error.POSITION_UNAVAILABLE:
                            message = '位置信息不可用';
                            break;
                        case error.TIMEOUT:
                            message = '定位超时';
                            break;
                    }
                    reject(new Error(message));
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 300000
                }
            );
        });
    }

    calculateDistance(lat1, lng1, lat2, lng2) {
        const R = 6371;
        const dLat = this.toRad(lat2 - lat1);
        const dLng = this.toRad(lng2 - lng1);
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(this.toRad(lat1)) * Math.cos(this.toRad(lat2)) *
            Math.sin(dLng / 2) * Math.sin(dLng / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    toRad(value) {
        return value * Math.PI / 180;
    }

    findNearestStation() {
        let minDistance = Infinity;
        let nearest = null;

        this.data.stations.forEach(station => {
            const distance = this.calculateDistance(
                this.userLocation.lat,
                this.userLocation.lng,
                station.lat,
                station.lng
            );

            if (distance < minDistance) {
                minDistance = distance;
                nearest = { ...station, distance };
            }
        });

        this.nearestStation = nearest;
        this.selectedLine = nearest.lines[0];
        this.selectedDirection = nearest.lines[0].directions[0];
    }

    setupUI() {
        this.loadingEl.style.display = 'none';
        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';

        this.stationNameEl.textContent = this.nearestStation.name;
        this.distanceEl.textContent = this.nearestStation.distance > 0
            ? `距离您 ${(this.nearestStation.distance * 1000).toFixed(0)} 米`
            : '已选择的地铁站';

        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    renderLineSelector() {
        this.lineSelectorEl.innerHTML = '';

        this.nearestStation.lines.forEach(line => {
            const btn = document.createElement('button');
            btn.className = `line-btn ${line.lineId === this.selectedLine.lineId ? 'active' : ''}`;
            btn.style.backgroundColor = line.lineId === this.selectedLine.lineId ? line.lineColor : '';
            btn.textContent = line.lineName;
            btn.onclick = () => this.selectLine(line);
            this.lineSelectorEl.appendChild(btn);
        });
    }

    renderDirectionSelector() {
        this.directionSelectorEl.innerHTML = '';

        this.selectedLine.directions.forEach(direction => {
            const btn = document.createElement('button');
            btn.className = `direction-btn ${direction.direction === this.selectedDirection.direction ? 'active' : ''}`;
            btn.textContent = direction.direction;
            btn.onclick = () => this.selectDirection(direction);
            this.directionSelectorEl.appendChild(btn);
        });
    }

    selectLine(line) {
        this.selectedLine = line;
        this.selectedDirection = line.directions[0];
        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    selectDirection(direction) {
        this.selectedDirection = direction;
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    updateTrainInfo() {
        const nextTrain = this.getNextTrain();
        if (!nextTrain) {
            this.trainTimeEl.textContent = '--:--';
            this.countdownEl.textContent = '已停运';
            this.trainInfoEl.textContent = '';
            return;
        }

        this.trainTimeEl.textContent = nextTrain.time;
        this.trainInfoEl.textContent = `${this.selectedLine.lineName} · ${this.selectedDirection.direction}`;
    }

    getNextTrain() {
        const now = new Date();
        const currentTime = now.getHours() * 60 + now.getMinutes();
        const schedule = this.selectedDirection.schedule.weekday;

        const firstTime = this.timeToMinutes(schedule.first);
        const lastTime = this.timeToMinutes(schedule.last);

        if (currentTime < firstTime || currentTime > lastTime) {
            return null;
        }

        const currentInterval = schedule.intervals.find(interval => {
            const start = this.timeToMinutes(interval.start);
            const end = this.timeToMinutes(interval.end);
            return currentTime >= start && currentTime < end;
        });

        if (!currentInterval) {
            return null;
        }

        let nextTrainTime = currentTime;
        const intervalStart = this.timeToMinutes(currentInterval.start);

        if (currentTime === intervalStart) {
            nextTrainTime = currentTime;
        } else {
            const timeSinceStart = currentTime - intervalStart;
            const intervalsPassed = Math.floor(timeSinceStart / currentInterval.interval);
            nextTrainTime = intervalStart + (intervalsPassed + 1) * currentInterval.interval;
        }

        if (nextTrainTime > lastTime) {
            return null;
        }

        return {
            time: this.minutesToTime(nextTrainTime),
            minutes: nextTrainTime
        };
    }

    timeToMinutes(timeStr) {
        const [hours, minutes] = timeStr.split(':').map(Number);
        return hours * 60 + minutes;
    }

    minutesToTime(minutes) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`;
    }

    startCountdown() {
        this.updateCountdown();
        this.countdownInterval = setInterval(() => {
            this.updateCountdown();
        }, 1000);
    }

    updateCountdown() {
        const nextTrain = this.getNextTrain();
        if (!nextTrain) {
            this.countdownEl.textContent = '已停运';
            return;
        }

        const now = new Date();
        const currentMinutes = now.getHours() * 60 + now.getMinutes();
        const currentSeconds = now.getSeconds();

        const timeDiff = nextTrain.minutes - currentMinutes;

        if (timeDiff < 0) {
            this.updateTrainInfo();
            return;
        }

        if (timeDiff === 0) {
            const secondsLeft = 60 - currentSeconds;
            if (secondsLeft <= 0) {
                this.updateTrainInfo();
                return;
            }
            this.countdownEl.textContent = `${secondsLeft} 秒后发车`;
        } else {
            const totalSeconds = timeDiff * 60 - currentSeconds;
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;
            this.countdownEl.textContent = `${minutes} 分 ${seconds} 秒后发车`;
        }
    }

    showError(message) {
        this.loadingEl.style.display = 'none';
        this.appEl.style.display = 'none';
        this.errorEl.style.display = 'block';
        this.errorEl.textContent = message;
    }

    showLocationFallback() {
        this.loadingEl.style.display = 'none';
        this.errorEl.style.display = 'block';
        this.errorEl.innerHTML = `
            <div style="text-align: center;">
                <p style="margin-bottom: 20px;">无法获取定位，请输入地铁站名：</p>
                <div style="margin-bottom: 20px;">
                    <input type="text" id="stationInput" placeholder="输入地铁站名搜索..." 
                           style="width: 100%; padding: 15px; border: none; border-radius: 10px; 
                                  background: rgba(255,255,255,0.9); color: #333; font-size: 16px;
                                  margin-bottom: 10px;">
                    <div id="searchResults" style="max-height: 200px; overflow-y: auto;"></div>
                </div>
            </div>
        `;

        const input = document.getElementById('stationInput');
        const results = document.getElementById('searchResults');

        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (!query) {
                results.innerHTML = '';
                return;
            }

            const filtered = this.data.stations.filter(station =>
                station.name.includes(query)
            );

            results.innerHTML = filtered.map(station =>
                `<button onclick="app.selectStationManually('${station.id}')" 
                 style="display: block; width: 100%; margin: 5px 0; padding: 12px; 
                        background: rgba(255,255,255,0.8); border: none; border-radius: 8px; 
                        color: #333; font-size: 15px; cursor: pointer; text-align: left;">
                    ${station.name}
                </button>`
            ).join('');
        });

        input.focus();
    }

    selectStationManually(stationId) {
        this.nearestStation = this.data.stations.find(s => s.id === stationId);
        this.nearestStation.distance = 0; // 手动选择时不显示距离
        this.selectedLine = this.nearestStation.lines[0];
        this.selectedDirection = this.nearestStation.lines[0].directions[0];

        this.setupUI();
        this.startCountdown();
    }
}

let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new NextTrainApp();
});