all:
	# export BUILDKIT_PROGRESS=plain
	docker buildx build \
			--cache-from type=registry,ref=pip-app:buildcache \
			.

venv:
	python3 -m venv venv
