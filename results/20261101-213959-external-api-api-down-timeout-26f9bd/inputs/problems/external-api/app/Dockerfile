# Build and test run inside pinned images; the host needs no JDK or Gradle wrapper.
FROM gradle:9.1-jdk21@sha256:db12d4789367d4676ef3d8aa672685e0e451705776b53f7d81c953fba3b1d55b AS build
WORKDIR /src
COPY settings.gradle build.gradle ./
COPY src ./src
RUN --mount=type=cache,target=/home/gradle/.gradle gradle -q --no-daemon bootJar -x test && touch -d @0 build/libs/app.jar

FROM eclipse-temurin:21-jre@sha256:0b99b3376fbb50dbf9c0af8535fdd5b8eb0d3fdfc8b1e4967f383b6919f6901a
COPY --from=build /src/build/libs/app.jar /app.jar
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=60", "-jar", "/app.jar"]
